"""北京时间工具 - 带缓存和降级策略"""
import threading
from datetime import datetime, timezone, timedelta
import time
import requests
from loguru import logger

BEIJING_TZ = timezone(timedelta(hours=8))

# 缓存：最多每60秒请求一次网络时间
_cached_time_offset = None
_last_sync_ts = 0
_SYNC_INTERVAL = 60
_time_lock = threading.Lock()


def _fetch_network_time():
    """从网络获取北京时间，返回与本地时钟的偏移量"""
    try:
        resp = requests.get(
            "http://worldtimeapi.org/api/timezone/Asia/Shanghai",
            timeout=3
        )
        if resp.status_code == 200:
            network_dt = datetime.fromisoformat(resp.json()["datetime"])
            local_now = datetime.now(timezone.utc).astimezone(BEIJING_TZ)
            return (network_dt - local_now).total_seconds()
    except Exception as e:
        logger.debug(f"网络时间同步失败: {e}")
    return None


def get_beijing_time() -> datetime:
    """
    获取北京时间。
    策略：首次调用同步网络时间，之后每60秒同步一次。
    网络不可用时降级为本地时钟。
    """
    global _cached_time_offset, _last_sync_ts

    now_ts = time.time()
    # 加锁防止并发竞态
    with _time_lock:
        if _cached_time_offset is None or (now_ts - _last_sync_ts) > _SYNC_INTERVAL:
            offset = _fetch_network_time()
            if offset is not None:
                _cached_time_offset = offset
                _last_sync_ts = now_ts

    local_beijing = datetime.now(timezone.utc).astimezone(BEIJING_TZ)
    if _cached_time_offset is not None:
        local_beijing += timedelta(seconds=_cached_time_offset)
    return local_beijing
