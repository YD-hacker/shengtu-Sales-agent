"""企微/微信推送 - 修复版

主要修复:
1. Webhook URL 从环境变量读取，提供清晰的缺失提示
2. 增加异步推送支持
3. 推送失败时记录更详细的错误信息
"""
import os
import time
import asyncio
import aiohttp
import requests
from loguru import logger

WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL", "")
# 修复: 检测 Webhook 是否配置
if not WEBHOOK_URL or "your_key" in WEBHOOK_URL:
    logger.warning("⚠️ WECHAT_WEBHOOK_URL 未配置或使用默认值，推送功能将模拟执行")

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]


def _is_configured():
    """检查 Webhook 是否已配置"""
    return bool(WEBHOOK_URL) and "your_key" not in WEBHOOK_URL


def _do_post(payload):
    """同步推送，带重试"""
    if not _is_configured():
        logger.info(f"[模拟推送] {payload.get('msgtype', 'unknown')}")
        return True  # 模拟成功

    for i, delay in enumerate(RETRY_BACKOFF):
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json.get("errcode") == 0:
                    return True
                logger.warning(f"推送API返回错误 (errcode={resp_json.get('errcode')}), "
                               f"第{i + 1}次重试")
            else:
                logger.warning(f"推送失败 (HTTP {resp.status_code}), 第{i + 1}次重试")
        except Exception as e:
            logger.warning(f"推送异常: {e}, 第{i + 1}次重试")
        if i < MAX_RETRIES - 1:
            time.sleep(delay)
    logger.error("推送三次均失败，放弃")
    return False


async def _do_post_async(payload):
    """异步推送，带重试"""
    if not _is_configured():
        logger.info(f"[模拟推送-异步] {payload.get('msgtype', 'unknown')}")
        return True

    timeout_cfg = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        for i, delay in enumerate(RETRY_BACKOFF):
            try:
                async with session.post(WEBHOOK_URL, json=payload) as resp:
                    if resp.status == 200:
                        resp_json = await resp.json()
                        if resp_json.get("errcode") == 0:
                            return True
                        logger.warning(f"异步推送API返回错误, 第{i + 1}次重试")
                    else:
                        logger.warning(f"异步推送失败 (HTTP {resp.status}), 第{i + 1}次重试")
            except Exception as e:
                logger.warning(f"异步推送异常: {e}, 第{i + 1}次重试")
            if i < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
    logger.error("异步推送三次均失败，放弃")
    return False


def push_report_info(user_id, state):
    """推送报备信息到企微"""
    fields = [
        ("姓名", state.get("name")),
        ("性别", state.get("gender")),
        ("学历", state.get("education")),
        ("毕业时间", state.get("graduated_year")),
        ("专业", state.get("major")),
        ("沟通岗位", state.get("target_position")),
        ("联系电话", state.get("phone")),
        ("出发城市", state.get("departure_city")),
        ("实训基地", state.get("campus_base")),
        ("到达时间", state.get("arrival_time")),
        ("是否需要住宿", state.get("need_accommodation")),
        ("其他备注", state.get("remarks"))
    ]
    lines = [f"- **{k}**：{v or '（未填）'}" for k, v in fields]
    content = "### 新学员报备\n" + "\n".join(lines)
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    success = _do_post(payload)
    if not success:
        logger.error(f"报备推送最终失败 user={user_id}")
    return success


def send_trial_reminder(user_id, message):
    """发送试听提醒"""
    payload = {"msgtype": "text", "text": {"content": message}}
    success = _do_post(payload)
    if not success:
        logger.error(f"试听提醒推送失败 user={user_id}")
    return success


def notify_human_takeover(user_id, state, trigger_reason=""):
    """通知销售团队接管对话

    触发场景:
    1. 用户主动要求转人工
    2. 高价值线索自动触发（trust >= 75 + 在关键阶段）
    3. 连续异议无法化解
    4. 多次情绪挫败
    """
    trust = state.get("trust_level", 50)
    current_node = state.get("current_node", "icebreak")
    direction = state.get("direction", "")
    education = state.get("education", "")
    city = state.get("city", "")
    is_qualified = state.get("is_qualified", False)

    # 构建用户画像摘要
    profile_parts = []
    if education:
        profile_parts.append(f"学历: {education}")
    if direction:
        profile_parts.append(f"方向: {direction}")
    if city:
        profile_parts.append(f"城市: {city}")
    profile_parts.append(f"信任: {trust}/100")
    profile_parts.append(f"阶段: {current_node}")
    if is_qualified:
        profile_parts.append("资格: 合格(保障班)")

    # 联系电话（销售需要回拨，不脱敏）
    phone = state.get("phone", "")

    content = (
        f"### 人工接管通知\n\n"
        f"**用户**: {user_id}\n\n"
        f"**触发原因**: {trigger_reason}\n\n"
        f"**用户画像**: {' | '.join(profile_parts)}\n\n"
        f"**联系电话**: {phone or '未收集'}\n\n"
        f"**AI状态**: 暖场陪聊中，等你来接手\n\n"
        f"> 请尽快在企业微信中回复该用户\n\n"
        f"> 超时30分钟AI将自动恢复服务"
    )

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    success = _do_post(payload)
    if success:
        logger.info(f"人工接管通知已发送 user={user_id} reason={trigger_reason}")
    else:
        logger.error(f"人工接管通知发送失败 user={user_id}")
    return success
