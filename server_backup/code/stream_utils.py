"""SSE 生成器工具 - 修复版

修复: 增加异常时发送 [DONE] 标记，确保客户端知道流结束
"""
from loguru import logger


async def sse_generator(user_id, msg, core_func):
    try:
        async for chunk in core_func(user_id, msg):
            yield f"data: {chunk}\n\n"
    except Exception as e:
        logger.error(f"SSE 流生成异常: {e}")
        yield f"data: 系统开小差了，请稍后再试。\n\n"
    # 修复: 确保始终发送 [DONE]
    yield "data: [DONE]\n\n"
