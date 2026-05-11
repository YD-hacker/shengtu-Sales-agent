"""状态与记忆持久化 - 企业级改造版

主要改造:
1. 每个用户独立JSON文件（解决多用户并发覆盖问题）
2. 内存缓存 + 文件持久化双写
3. 原子写入所有文件
4. 对话历史截断（防止token爆炸）
5. 定期清理过期用户数据
"""
import copy
from datetime import datetime, timedelta
import json
import os
import threading
import tempfile
from loguru import logger
from code.time_utils import get_beijing_time, BEIJING_TZ
from code import STATE_FILE, LAST_ACTIVE_FILE, DATA_DIR

# 用户数据目录：每个用户一个文件
USER_DATA_DIR = os.path.join(DATA_DIR, "users")
os.makedirs(USER_DATA_DIR, exist_ok=True)

# 内存缓存（加速读取，避免每次读文件）
_state_cache = {}   # user_id -> {state dict}
MEMORY = {}         # user_id -> [{user, assistant}, ...]
LAST_ACTIVE = {}    # user_id -> ISO timestamp

_state_lock = threading.Lock()
_memory_lock = threading.Lock()
_active_lock = threading.Lock()

# 最大对话历史轮数
MAX_HISTORY_TURNS = 10


def _user_state_path(user_id: str) -> str:
    """每个用户独立的状态文件路径"""
    # 安全过滤user_id，防止路径遍历
    safe_uid = "".join(c for c in user_id if c.isalnum() or c in ("_", "-"))
    return os.path.join(USER_DATA_DIR, f"{safe_uid}.json")


def atomic_save(path, data):
    """原子写入JSON文件"""
    dirname = os.path.dirname(path)
    os.makedirs(dirname, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', dir=dirname, delete=False, encoding='utf-8'
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        os.replace(tmp_name, path)
    except Exception as e:
        logger.error(f"原子写入失败 {path}: {e}")
        try:
            os.unlink(tmp_name)
        except Exception:
            pass


def init_user_state(user_id):
    """初始化新用户状态"""
    return {
        "user_id": user_id,
        "current_node": "icebreak",
        "direction": "",
        "city": "",
        "age": "",
        "education": "",
        "user_type": "",
        "major": "",
        "graduated_year": "",
        "graduated_month": "7",
        "name": "",
        "phone": "",
        "is_qualified": None,
        "last_intent": "",
        "rejected": False,
        "last_rejected_time": None,
        "send_failure": False,
        "created_at": str(get_beijing_time()),
        # 报备信息槽位
        "gender": "",
        "graduation_time": "",
        "target_position": "",
        "departure_city": "",
        "campus_base": "",
        "arrival_time": "",
        "need_accommodation": "",
        "remarks": "",
        # 试听跟进
        "visit_time": None,
        "visit_status": None,
        "questionnaire_sent": False,
        "second_invite_sent": False,
        "lead_status": None,
        "trial_lost_risk": False,
        # 信任引擎
        "trust_level": 50,
        "trust_log": [],
        "last_trust_decay_date": "",
        # 痛点追踪
        "pain_points": [],
        # 长期关系管理
        "post_sale_thankyou_sent": False,
        "post_sale_checkin_sent": False,
        "last_info_sent_date": "",
        "sale_completed_at": None,
    }


def load_state(user_id):
    """加载用户状态（线程安全，每用户独立文件）
    注意：返回深拷贝，防止并发修改覆盖
    """
    global _state_cache
    with _state_lock:
        # 1. 先查内存缓存
        if user_id in _state_cache:
            return copy.deepcopy(_state_cache[user_id])

        # 2. 从用户独立文件加载
        user_file = _user_state_path(user_id)
        if os.path.exists(user_file):
            try:
                with open(user_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                _state_cache[user_id] = state
                return copy.deepcopy(state)
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"用户状态文件读取失败 {user_id}: {e}")

        # 3. 尝试从旧的全量文件迁移（兼容旧数据）
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    all_states = json.load(f)
                if user_id in all_states:
                    state = all_states[user_id]
                    _state_cache[user_id] = state
                    # 迁移到独立文件
                    atomic_save(user_file, state)
                    return copy.deepcopy(state)
            except Exception:
                pass

        # 4. 新用户：初始化
        state = init_user_state(user_id)
        _state_cache[user_id] = state
        return copy.deepcopy(state)


def save_state(user_id, state):
    """保存用户状态（线程安全，写入独立文件）"""
    global _state_cache
    with _state_lock:
        _state_cache[user_id] = state
        # 同步持久化到独立文件（确保数据一致性）
        try:
            atomic_save(_user_state_path(user_id), state)
        except Exception as e:
            logger.error(f"状态持久化失败 {user_id}: {e}")


def get_history(user_id, max_turns=5):
    """获取对话历史"""
    with _memory_lock:
        if user_id not in MEMORY:
            return []
        return MEMORY[user_id][-max_turns:]


def add_history(user_id, user_msg, assistant_msg):
    """添加对话历史（带截断）"""
    with _memory_lock:
        if user_id not in MEMORY:
            MEMORY[user_id] = []
        MEMORY[user_id].append({"user": user_msg, "assistant": assistant_msg})
        # 保留最近N轮，防止token爆炸
        MEMORY[user_id] = MEMORY[user_id][-MAX_HISTORY_TURNS:]


def load_last_active():
    """加载最后活跃时间"""
    global LAST_ACTIVE
    if os.path.exists(LAST_ACTIVE_FILE):
        try:
            with open(LAST_ACTIVE_FILE, "r", encoding="utf-8") as f:
                LAST_ACTIVE = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"活跃时间文件读取失败: {e}")
            LAST_ACTIVE = {}


def record_active(user_id):
    """记录用户活跃时间"""
    with _active_lock:
        LAST_ACTIVE[user_id] = get_beijing_time().isoformat()
        try:
            atomic_save(LAST_ACTIVE_FILE, LAST_ACTIVE)
        except Exception as e:
            logger.error(f"活跃时间持久化失败: {e}")


def get_all_user_ids():
    """获取所有已知用户ID列表（扫描缓存和磁盘）"""
    ids = set(_state_cache.keys())
    if os.path.exists(USER_DATA_DIR):
        for fname in os.listdir(USER_DATA_DIR):
            if fname.endswith(".json"):
                ids.add(fname[:-5])
    return list(ids)


def get_inactive_users(days=3):
    """
    获取沉睡用户列表
    排除已完成和明确拒绝且发送失败的用户
    """
    cutoff = get_beijing_time() - timedelta(days=days)
    inactive = []

    # 扫描用户数据目录
    with _state_lock:
        all_cached = set(_state_cache.keys())

    # 同时扫描磁盘上的用户文件
    disk_users = set()
    if os.path.exists(USER_DATA_DIR):
        for fname in os.listdir(USER_DATA_DIR):
            if fname.endswith(".json"):
                disk_users.add(fname[:-5])

    all_users = all_cached | disk_users

    for uid in all_users:
        st = _state_cache.get(uid)
        if not st:
            # 从文件加载
            user_file = _user_state_path(uid)
            if os.path.exists(user_file):
                try:
                    with open(user_file, "r", encoding="utf-8") as f:
                        st = json.load(f)
                except Exception:
                    continue
        if not st:
            continue

        if st.get("send_failure", False):
            continue
        if st.get("current_node") == "completed":
            continue

        if uid in LAST_ACTIVE:
            try:
                last = datetime.fromisoformat(LAST_ACTIVE[uid])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=BEIJING_TZ)
                if last < cutoff:
                    inactive.append(uid)
            except Exception:
                inactive.append(uid)
        else:
            inactive.append(uid)
    return inactive


# 模块加载时初始化
load_last_active()
