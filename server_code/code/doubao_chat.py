"""生成回复封装 - 无需修改"""
from code.agent_core import process_message_stream


async def generate_reply(user_id, msg):
    """非流式生成完整回复"""
    full = ""
    async for token in process_message_stream(user_id, msg):
        full += token
    return full
