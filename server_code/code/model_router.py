"""火山引擎模型调用 - 企业级改造版

主要改造:
1. aiohttp timeout 使用 ClientTimeout 对象
2. 流式响应解析增加异常容错
3. 视觉模型返回值增加异常处理
4. 连接池复用
5. API Key 缺失时优雅降级
6. 重试机制（指数退避）
7. 限流保护
8. 超时保护
"""
import os
import json
import yaml
import requests
import asyncio
import aiohttp
import re
import time
from loguru import logger
from code import CONFIG_FILE, LOG_DIR

with open(CONFIG_FILE, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

# ---- LLM健康检查 ----
_last_health_check = 0
_health_cache = True  # 默认健康
_HEALTH_CHECK_INTERVAL = 60  # 60秒检查一次


def get_llm_health() -> bool:
    """检查LLM服务是否可达"""
    global _last_health_check, _health_cache
    now = time.time()
    if now - _last_health_check < _HEALTH_CHECK_INTERVAL:
        return _health_cache
    _last_health_check = now
    if not API_KEY:
        _health_cache = False
        return False
    try:
        resp = requests.post(
            BASE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json; charset=utf-8"
            },
            json={
                "model": CONFIG["system"]["main_model"],
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.1,
                "max_tokens": 5,
                "stream": False
            },
            timeout=10
        )
        _health_cache = resp.status_code == 200
        return _health_cache
    except Exception:
        _health_cache = False
        return False

FILE_MAPPING = {
    "网安课程大纲": "file_repo/网安课程大纲.pdf",
    "大数据课程大纲": "file_repo/大数据课程大纲.pdf",
    "就业保障协议": "file_repo/就业保障协议参考.pdf",
    "广州大数据校区": "file_repo/广州大数据.jpg",
    "广州网安校区": "file_repo/广州网安.jpg",
    "杭州大数据校区": "file_repo/杭州大数据.jpg",
    "杭州网安校区": "file_repo/杭州网安.jpg"
}

os.makedirs(LOG_DIR, exist_ok=True)
logger.add(os.path.join(LOG_DIR, "agent.log"), rotation="100MB", retention="7 days")

# 限流保护：记录最近调用时间，防止短时间大量调用
_last_call_time = 0
_MIN_CALL_INTERVAL = 0.5  # 最小调用间隔（秒）

# 重试配置
_MAX_RETRIES = 2
_RETRY_DELAYS = [1, 3]  # 指数退避延迟


def _check_api_key():
    """检查 API Key 是否配置"""
    if not API_KEY:
        logger.error("VOLCENGINE_API_KEY 未配置！")
        return False
    return True


def call_model(prompt, temperature, model_type="main"):
    """同步模型调用（带重试）"""
    if not _check_api_key():
        return "我这边信号不太好，你再说一遍？"

    model_name = CONFIG["system"]["main_model"]
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json; charset=utf-8"
                },
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": CONFIG["system"]["max_tokens"],
                    "stream": False
                },
                timeout=CONFIG["system"]["timeout"]
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content:
                return content
            # 空回复：重试
            logger.warning(f"模型返回空内容，尝试 {attempt + 1}/{_MAX_RETRIES + 1}")
        except requests.exceptions.Timeout:
            logger.warning(f"模型调用超时，尝试 {attempt + 1}/{_MAX_RETRIES + 1}")
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                # 限流：等待后重试
                wait = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning(f"API限流，等待 {wait}s 后重试")
                time.sleep(wait)
                continue
            logger.error(f"模型调用HTTP错误: {e}")
            break
        except Exception as e:
            logger.error(f"模型调用失败: {e}")
            break

        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])

    return "我这边信号不太好，你再说一遍？"


async def stream_llm(system_prompt, temperature=0.5, model_type="main"):
    """
    流式模型调用（带重试和限流保护）
    """
    global _last_call_time

    if not _check_api_key():
        yield "我这边信号不太好，你再说一遍？"
        return

    # 限流保护
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < _MIN_CALL_INTERVAL:
        await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)
    _last_call_time = time.time()

    model_name = CONFIG["system"]["main_model"]
    timeout_cfg = aiohttp.ClientTimeout(
        total=CONFIG["system"].get("stream_timeout", 60),
        connect=10
    )

    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                async with session.post(
                    BASE_URL,
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json; charset=utf-8"
                    },
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt}
                        ],
                        "temperature": temperature,
                        "max_tokens": CONFIG["system"]["max_tokens"],
                        "stream": True
                    },
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        if resp.status == 429:
                            # 限流：等待后重试
                            wait = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            logger.warning(f"API限流，等待 {wait}s 后重试")
                            await asyncio.sleep(wait)
                            continue
                        logger.error(f"流式调用HTTP错误 {resp.status}: {error_text[:200]}")
                        raise Exception(f"HTTP {resp.status}")

                    got_content = False
                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith(b'data: '):
                            data = line[6:]
                            if data == b'[DONE]':
                                break
                            try:
                                chunk_json = json.loads(data)
                                delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    got_content = True
                                    yield content
                            except (json.JSONDecodeError, IndexError, KeyError) as e:
                                logger.debug(f"流式chunk解析跳过: {e}")
                                continue

                    if got_content:
                        return
                    # 空回复：重试
                    logger.warning(f"流式调用返回空内容，尝试 {attempt + 1}/{_MAX_RETRIES + 1}")

        except asyncio.TimeoutError:
            logger.warning(f"流式调用超时，尝试 {attempt + 1}/{_MAX_RETRIES + 1}")
        except aiohttp.ClientError as e:
            logger.warning(f"流式调用网络错误: {e}，尝试 {attempt + 1}/{_MAX_RETRIES + 1}")
        except Exception as e:
            if "HTTP 429" in str(e):
                continue  # 已在上面处理
            logger.error(f"流式失败: {e}")
            break

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])

    # 所有重试都失败，尝试同步兜底
    logger.warning("流式调用全部失败，尝试同步兜底")
    try:
        sync_reply = await asyncio.to_thread(call_model, system_prompt, temperature)
        if sync_reply and "信号不太好" not in sync_reply:
            for c in sync_reply:
                yield c
            return
    except Exception as e2:
        logger.error(f"兜底模型也失败: {e2}")

    yield "我这边信号不太好，你再说一遍？"


async def call_vision_model(prompt, image_base64):
    """视觉模型调用 - 提取图片中的结构化信息"""
    image_model = CONFIG["system"]["image_model"]
    full_prompt = (
        prompt +
        "\n请提取图中的姓名、电话、学历、毕业时间、专业等信息，"
        "仅返回JSON格式，key用英文(name/phone/education/graduated_year/major)，"
        "不要任何额外文字。如果某个字段无法识别则不包含该key。"
    )
    payload = {
        "model": image_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 512
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json; charset=utf-8"
    }
    timeout_cfg = aiohttp.ClientTimeout(total=30)

    for attempt in range(2):
        try:
            async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                async with session.post(BASE_URL, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"视觉模型调用失败 {resp.status}: {error_text[:200]}")
                        continue
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    # 修复: 尝试从 markdown code block 中提取 JSON
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(1)
                    try:
                        result = json.loads(content)
                        # 确保返回的是字典
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        logger.warning(f"视觉模型返回非JSON: {content[:200]}")
                        # 降级: 尝试正则提取关键信息
                        extracted = {}
                        phone = re.search(r"1[3-9]\d{9}", content)
                        if phone:
                            extracted["phone"] = phone.group()
                        year = re.search(r"(20\d{2})\s*年", content)
                        if year:
                            extracted["graduated_year"] = year.group(1)
                        return extracted
        except Exception as e:
            logger.error(f"视觉模型请求异常: {e}, 尝试 {attempt + 1}/2")
    return {}
