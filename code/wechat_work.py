"""企业微信自建应用接口模块

功能：
1. 回调验证（GET echostr）
2. 消息解密/加密（AES）
3. 获取 access_token（带缓存）
4. 发送消息给用户
5. 转发消息给 Agent 处理

接入流程：
1. 企微管理后台 → 应用管理 → 创建自建应用
2. 设置接收消息的 URL: http://你的服务器:8080/callback/wechat_work
3. 设置 Token 和 EncodingAESKey
4. 将 corpid/agentid/secret/token/encoding_aes_key 填入 .env
"""
import os
import time
import json
import hashlib
import base64
import struct
import socket
import threading
import requests
import xml.etree.ElementTree as ET
from loguru import logger
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ---------- 配置 ----------
CORPID = os.getenv("WECHAT_CORPID", "")
CORPSECRET = os.getenv("WECHAT_CORPSECRET", "")
AGENTID = int(os.getenv("WECHAT_AGENTID", "0"))
TOKEN = os.getenv("WECHAT_TOKEN", "")
ENCODING_AES_KEY = os.getenv("WECHAT_ENCODING_AES_KEY", "")

_configured = bool(CORPID and CORPSECRET and AGENTID and TOKEN and ENCODING_AES_KEY)
if not _configured:
    logger.warning("企微自建应用未配置，回调功能将模拟执行。请在 .env 中设置 WECHAT_CORPID/WECHAT_CORPSECRET/WECHAT_AGENTID/WECHAT_TOKEN/WECHAT_ENCODING_AES_KEY")

# ---------- access_token 缓存 ----------
_token_cache = {"token": "", "expires_at": 0}
_token_lock = threading.Lock()


def _get_encoding_aes_key_bytes():
    """将 EncodingAESKey 转为 AES 密钥（32字节）"""
    key = ENCODING_AES_KEY + "="
    return base64.b64decode(key)[:32]


def decrypt_message(encrypted_msg):
    """解密企微消息"""
    if not _configured:
        return encrypted_msg  # 未配置时直接返回原文
    try:
        aes_key = _get_encoding_aes_key_bytes()
        iv = aes_key[:16]
        encrypted_data = base64.b64decode(encrypted_msg)

        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        plain = decryptor.update(encrypted_data) + decryptor.finalize()

        # 去除 PKCS7 padding
        pad_len = plain[-1]
        plain = plain[:-pad_len]

        # 解析: 16字节随机 + 4字节消息长度 + 消息内容 + CorpID
        msg_len = struct.unpack("!I", plain[16:20])[0]
        msg_content = plain[20:20 + msg_len].decode("utf-8")
        from_corpid = plain[20 + msg_len:].decode("utf-8")

        if from_corpid != CORPID:
            logger.warning(f"CorpID 不匹配: {from_corpid} != {CORPID}")
            return None

        return msg_content
    except Exception as e:
        logger.error(f"消息解密失败: {e}")
        return None


def encrypt_message(reply_msg, nonce, timestamp):
    """加密回复消息"""
    if not _configured:
        return reply_msg
    try:
        aes_key = _get_encoding_aes_key_bytes()
        iv = aes_key[:16]

        # 构造明文: 16字节随机 + 4字节长度 + 消息 + CorpID
        random_bytes = os.urandom(16)
        msg_bytes = reply_msg.encode("utf-8")
        msg_len = struct.pack("!I", len(msg_bytes))
        corp_bytes = CORPID.encode("utf-8")
        plain = random_bytes + msg_len + msg_bytes + corp_bytes

        # PKCS7 padding
        block_size = 32
        pad_len = block_size - (len(plain) % block_size)
        plain += bytes([pad_len] * pad_len)

        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(plain) + encryptor.finalize()

        return base64.b64encode(encrypted).decode("utf-8")
    except Exception as e:
        logger.error(f"消息加密失败: {e}")
        return None


def verify_signature(signature, timestamp, nonce, echostr=None):
    """验证回调签名"""
    if not _configured:
        return echostr or "success"
    items = sorted([TOKEN, timestamp, nonce])
    if echostr:
        items.append(echostr)
    hash_str = "".join(items)
    computed = hashlib.sha1(hash_str.encode("utf-8")).hexdigest()
    if computed == signature:
        return echostr or "success"
    logger.warning(f"签名验证失败: {computed} != {signature}")
    return None


def get_access_token():
    """获取 access_token（带缓存，过期前200秒刷新）"""
    if not _configured:
        return ""
    with _token_lock:
        now = time.time()
        if _token_cache["token"] and _token_cache["expires_at"] > now + 200:
            return _token_cache["token"]

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {"corpid": CORPID, "corpsecret": CORPSECRET}
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                _token_cache["token"] = data["access_token"]
                _token_cache["expires_at"] = now + data.get("expires_in", 7200)
                logger.info("企微 access_token 获取成功")
                return _token_cache["token"]
            else:
                logger.error(f"获取 access_token 失败: {data}")
                return ""
        except Exception as e:
            logger.error(f"获取 access_token 异常: {e}")
            return ""


def send_text_message(user_id, content):
    """发送文本消息给用户"""
    if not _configured:
        logger.info(f"[模拟企微推送] -> {user_id}: {content[:50]}...")
        return True

    token = get_access_token()
    if not token:
        logger.error("无法获取 access_token，消息发送失败")
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "text",
        "agentid": AGENTID,
        "text": {"content": content}
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info(f"企微消息发送成功: {user_id}")
            return True
        else:
            logger.error(f"企微消息发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"企微消息发送异常: {e}")
        return False


def send_markdown_message(user_id, content):
    """发送 Markdown 消息（企业微信内部应用支持）"""
    if not _configured:
        logger.info(f"[模拟企微Markdown推送] -> {user_id}: {content[:50]}...")
        return True

    token = get_access_token()
    if not token:
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "markdown",
        "agentid": AGENTID,
        "markdown": {"content": content}
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        else:
            logger.error(f"Markdown消息发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"Markdown消息发送异常: {e}")
        return False


def parse_callback_xml(xml_data):
    """解析企微回调 XML 消息"""
    try:
        root = ET.fromstring(xml_data)
        msg = {}
        for child in root:
            msg[child.tag] = child.text
        return msg
    except Exception as e:
        logger.error(f"XML 解析失败: {e}")
        return None


def handle_callback_request(request_obj):
    """处理企微回调请求（供 app.py 调用）

    Args:
        request_obj: Flask request 对象

    Returns:
        (status_code, response_text)
    """
    # GET: 回调验证
    if request_obj.method == "GET":
        signature = request_obj.args.get("signature", "")
        timestamp = request_obj.args.get("timestamp", "")
        nonce = request_obj.args.get("nonce", "")
        echostr = request_obj.args.get("echostr", "")

        result = verify_signature(signature, timestamp, nonce, echostr)
        if result:
            return 200, result
        return 403, "Verification failed"

    # POST: 接收消息
    try:
        raw_data = request_obj.get_data(as_text=True)
        msg = parse_callback_xml(raw_data)

        if not msg:
            return 200, "success"

        # 处理加密消息
        if "Encrypt" in msg and _configured:
            decrypted = decrypt_message(msg["Encrypt"])
            if decrypted:
                msg = parse_callback_xml(decrypted)
                if not msg:
                    return 200, "success"

        msg_type = msg.get("MsgType", "")
        from_user = msg.get("FromUserName", "")
        content = ""

        if msg_type == "text":
            content = msg.get("Content", "")
        elif msg_type == "image":
            content = "[图片消息]"
        elif msg_type == "voice":
            content = msg.get("Recognition", "[语音消息]")
        elif msg_type == "event":
            event = msg.get("Event", "")
            if event == "enter_agent":
                content = "你好"
            else:
                logger.info(f"企微事件: {event}")
                return 200, "success"
        else:
            logger.info(f"不支持的消息类型: {msg_type}")
            return 200, "success"

        if not content or not from_user:
            return 200, "success"

        logger.info(f"企微收到消息: {from_user} -> {content[:50]}")

        # 异步调用 Agent 处理（避免阻塞企微回调）
        threading.Thread(
            target=_process_and_reply,
            args=(from_user, content),
            daemon=True
        ).start()

        return 200, "success"

    except Exception as e:
        logger.error(f"处理企微回调异常: {e}")
        return 200, "success"


def _process_and_reply(from_user, content):
    """调用 Agent 处理消息并回复（在独立线程中运行）"""
    try:
        import asyncio
        from code.agent_core import process_message_stream

        loop = asyncio.new_event_loop()
        try:
            chunks = []

            async def collect():
                async for token in process_message_stream(from_user, content):
                    if token:
                        chunks.append(token)

            loop.run_until_complete(collect())
            reply = "".join(chunks)

            if reply:
                send_text_message(from_user, reply)
                logger.info(f"企微回复已发送: {from_user} -> {reply[:50]}")
            else:
                logger.warning(f"Agent 返回空回复: {from_user}")
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Agent 处理失败: {e}")
        send_text_message(from_user, "我这边出了点小问题，稍后再试试？")
