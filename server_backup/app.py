"""Flask 主服务 - 企业级交付版

升级点:
1. API鉴权（Token验证）
2. 限流保护
3. 健康检查增强（含LLM/存储连通性）
4. 输入长度校验
5. 日志脱敏
6. LLM降级提示优化
7. 优雅关闭
8. 并发安全的asyncio loop管理
"""
from flask import Flask, request, Response, jsonify, abort
import asyncio
import sys
import traceback
import atexit
import time
import re
import yaml
from loguru import logger
from code.agent_core import process_message_stream, MAX_MSG_LENGTH
from code.doubao_chat import generate_reply
from code.scheduler import start_scheduler, scheduler
from code.model_router import call_vision_model, get_llm_health
from code.memory_manager import load_state, save_state
from code import CONFIG_FILE

# ---------- 加载配置 ----------
with open(CONFIG_FILE, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# ---------- API鉴权配置 ----------
API_AUTH = CONFIG.get("api_auth", {})
RATE_LIMIT = API_AUTH.get("rate_limit", {})

# ---------- 日志配置 ----------
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ---------- 限流计数器 ----------
_rate_limit_store = {}  # token -> {"minute": (timestamp, count), "hour": (timestamp, count)}


def _check_rate_limit(token: str) -> bool:
    """检查限流"""
    if not RATE_LIMIT.get("enabled", False):
        return True

    now = time.time()
    if token not in _rate_limit_store:
        _rate_limit_store[token] = {"minute": (now, 0), "hour": (now, 0)}

    store = _rate_limit_store[token]

    # 每分钟限流
    minute_ts, minute_count = store["minute"]
    if now - minute_ts > 60:
        store["minute"] = (now, 0)
        minute_count = 0
    else:
        minute_count += 1
        store["minute"] = (minute_ts, minute_count)
    max_per_minute = RATE_LIMIT.get("max_requests_per_minute", 30)
    if minute_count > max_per_minute:
        return False

    # 每小时限流
    hour_ts, hour_count = store["hour"]
    if now - hour_ts > 3600:
        store["hour"] = (now, 0)
        hour_count = 0
    else:
        hour_count += 1
        store["hour"] = (hour_ts, hour_count)
    max_per_hour = RATE_LIMIT.get("max_requests_per_hour", 200)
    if hour_count > max_per_hour:
        return False

    return True


def _check_auth():
    """API鉴权检查"""
    if not API_AUTH.get("enabled", False):
        return True

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.headers.get("X-API-Key", "")

    valid_tokens = API_AUTH.get("tokens", [])
    if token in valid_tokens:
        if not _check_rate_limit(token):
            abort(429, description="请求过于频繁，请稍后再试")
        return True

    abort(401, description="未授权访问，请提供有效的API Token")


# ---------- 统一异常拦截 ----------
@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(429)
@app.errorhandler(500)
def handle_http_error(e):
    code = getattr(e, 'code', 500)
    desc = getattr(e, 'description', str(e))
    logger.error(f"HTTP错误 {code}: {request.url} - {desc}")
    return jsonify({"error": desc, "code": code}), code


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.error(f"未捕获异常: {request.url}\n{traceback.format_exc()}")
    return jsonify({"error": "系统开小差了，请稍后再试", "code": 500}), 500


def validate_json(required=None):
    """请求验证装饰器"""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                abort(400, description="仅支持JSON请求")
            data = request.get_json(silent=True)
            if data is None:
                abort(400, description="JSON格式错误")
            if required:
                for field in required:
                    if field not in data or not data[field]:
                        abort(400, description=f"缺少必要字段: {field}")
            # 输入长度校验
            msg = data.get("msg", "")
            if msg and len(msg) > MAX_MSG_LENGTH:
                abort(400, description=f"消息长度不能超过{MAX_MSG_LENGTH}字符")
            kwargs['json_data'] = data
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------- 路由 ----------
@app.route('/health')
def health():
    """增强版健康检查 - 含依赖状态和版本信息"""
    health_info = {
        "status": "ok",
        "timestamp": time.time(),
        "version": "3.0.0-intelligent"
    }

    # 检查LLM连通性
    llm_ok = get_llm_health()
    health_info["llm"] = "ok" if llm_ok else "degraded"

    # 检查LLM熔断状态
    try:
        from code.agent_core import _llm_fuse_open, _llm_fail_count
        health_info["llm_fuse_open"] = _llm_fuse_open
        health_info["llm_fail_count"] = _llm_fail_count
    except Exception:
        pass

    # 检查存储
    try:
        from code import DATA_DIR
        import os
        health_info["storage"] = "ok" if os.path.exists(DATA_DIR) else "error"
        # 检查用户数据目录
        user_dir = os.path.join(DATA_DIR, "users")
        user_count = len([f for f in os.listdir(user_dir) if f.endswith('.json')]) if os.path.exists(user_dir) else 0
        health_info["user_count"] = user_count
    except Exception:
        health_info["storage"] = "error"

    # 检查调度器
    try:
        health_info["scheduler"] = "running" if scheduler.running else "stopped"
    except Exception:
        health_info["scheduler"] = "unknown"

    # 检查API鉴权状态
    health_info["auth_enabled"] = API_AUTH.get("enabled", False)

    # 健康状态判定
    if not llm_ok:
        health_info["status"] = "degraded"
        # LLM降级时触发告警（有冷却）
        try:
            from code.error_monitor import alert_health_check_failed
            alert_health_check_failed("LLM", "LLM服务不可达，系统运行在降级模式")
        except Exception:
            pass

    status_code = 200 if health_info["status"] == "ok" else 503
    return jsonify(health_info), status_code


@app.route('/test/chat', methods=['POST'])
@validate_json(required=['user_id', 'msg'])
def chat(json_data=None):
    user_id = json_data['user_id']
    msg = json_data['msg']
    stream = json_data.get('stream', True)

    # API鉴权
    _check_auth()

    if not stream:
        loop = asyncio.new_event_loop()
        try:
            reply = loop.run_until_complete(generate_reply(user_id, msg))
        finally:
            loop.close()
        return jsonify({"reply": reply})

    # 流式模式
    def generate():
        loop = None
        try:
            loop = asyncio.new_event_loop()

            async def collect_stream():
                chunks = []
                async for token in process_message_stream(user_id, msg):
                    chunks.append(token)
                return chunks

            chunks = loop.run_until_complete(collect_stream())

            for chunk in chunks:
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"

        except GeneratorExit:
            logger.info(f"SSE客户端断开 user={user_id}")
        except Exception as e:
            logger.error(f"SSE生成异常: {e}")
            yield f"data: 系统开小差了，请稍后再试\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if loop and not loop.is_closed():
                loop.close()

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/upload/image', methods=['POST'])
@validate_json(required=['user_id', 'image_base64'])
def upload_image(json_data=None):
    _check_auth()

    user_id = json_data['user_id']
    image = json_data['image_base64']
    if len(image) > 15 * 1024 * 1024:
        abort(400, description="图片过大，请压缩后上传")
    try:
        loop = asyncio.new_event_loop()
        try:
            extracted = loop.run_until_complete(
                call_vision_model(
                    "提取图中的姓名、电话、学历、毕业年份、专业等信息", image
                )
            )
        finally:
            loop.close()

        state = load_state(user_id)

        valid_keys = {
            "name", "phone", "education", "graduated_year",
            "graduated_month", "major", "direction"
        }
        updated_fields = {}
        for k, v in extracted.items():
            if k in valid_keys and v:
                state[k] = str(v)
                # 日志脱敏
                log_v = re.sub(r'(1[3-9]\d)\d{4}(\d{3})', r'\1****\2', str(v)) if k == "phone" else v
                updated_fields[k] = log_v

        save_state(user_id, state)
        logger.info(f"图片提取更新字段: {updated_fields}")
        return jsonify({"status": "ok", "extracted": updated_fields})

    except Exception as e:
        logger.error(f"图片处理失败: {e}")
        return jsonify({"status": "error", "msg": "图片分析失败，请稍后再试"}), 500


@app.route('/callback/wechat_work', methods=['GET', 'POST'])
def wechat_work_callback():
    if request.method == 'GET':
        return "success"
    msg_data = request.get_json(silent=True) or {}
    logger.info(f"企业微信回调消息: {msg_data}")
    return "success"


@app.route('/callback/wechat_personal', methods=['GET', 'POST'])
def wechat_personal_callback():
    if request.method == 'GET':
        return "success"
    msg_data = request.get_json(silent=True) or {}
    logger.info(f"个人微信回调消息: {msg_data}")
    return "success"


@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    """运营数据看板"""
    _check_auth()
    try:
        from code.conversation_analytics import get_dashboard_data
        from code.lead_scorer import get_lead_grade
        data = get_dashboard_data()
        return jsonify(data)
    except Exception as e:
        logger.error(f"获取看板数据失败: {e}")
        return jsonify({"error": "获取数据失败"}), 500


@app.route('/api/user/<user_id>/score', methods=['GET'])
def user_score(user_id):
    """查询用户线索分"""
    _check_auth()
    try:
        from code.memory_manager import load_state
        from code.lead_scorer import calculate_lead_score, get_lead_grade, get_lead_strategy
        state = load_state(user_id)
        score = calculate_lead_score(state)
        grade = get_lead_grade(score)
        strategy = get_lead_strategy(score)
        return jsonify({
            "user_id": user_id,
            "lead_score": score,
            "lead_grade": grade,
            "strategy": strategy,
            "current_node": state.get("current_node", "icebreak"),
            "trust_level": state.get("trust_level", 50),
        })
    except Exception as e:
        logger.error(f"查询用户分数失败: {e}")
        return jsonify({"error": "查询失败"}), 500


@app.route('/api/experiments', methods=['GET'])
def experiments_status():
    """查看A/B实验状态"""
    _check_auth()
    try:
        from code.experiment_manager import get_active_experiments, evaluate_experiment
        active = get_active_experiments()
        results = []
        for exp in active:
            evaluation = evaluate_experiment(exp["name"])
            results.append({
                "name": exp["name"],
                "status": exp.get("status"),
                "description": exp.get("description", ""),
                "evaluation": evaluation,
            })
        return jsonify({"experiments": results})
    except Exception as e:
        logger.error(f"获取实验状态失败: {e}")
        return jsonify({"error": "获取失败"}), 500



@app.route('/api/analytics', methods=['GET'])
def analytics_dashboard():
    """数据分析仪表盘"""
    _check_auth()
    try:
        from code.analytics_dashboard import get_dashboard_data
        data = get_dashboard_data()
        return jsonify(data)
    except Exception as e:
        logger.error(f"获取分析数据失败: {e}")
        return jsonify({"error": "获取数据失败"}), 500


@app.route('/api/analytics/funnel', methods=['GET'])
def conversion_funnel():
    """转化漏斗"""
    _check_auth()
    try:
        from code.analytics_dashboard import get_funnel_data
        return jsonify(get_funnel_data())
    except Exception as e:
        logger.error(f"获取漏斗数据失败: {e}")
        return jsonify({"error": "获取失败"}), 500


@app.route('/api/experiments/auto', methods=['POST'])
def auto_experiments():
    """自动创建A/B实验"""
    _check_auth()
    try:
        from code.auto_experiment import auto_create_experiments
        from code.state_machine import KB
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            experiments = loop.run_until_complete(auto_create_experiments(KB))
        finally:
            loop.close()
        return jsonify({"status": "ok", "experiments_created": len(experiments)})
    except Exception as e:
        logger.error(f"自动创建实验失败: {e}")
        return jsonify({"error": "创建失败"}), 500


@app.route('/api/vector_memory/stats', methods=['GET'])
def vector_memory_stats():
    """向量记忆统计"""
    _check_auth()
    try:
        from code.memory_vector import vector_memory
        stats = vector_memory.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"获取向量记忆统计失败: {e}")
        return jsonify({"error": "获取失败"}), 500


@app.route('/api/user/<user_id>/profile', methods=['GET'])
def user_profile(user_id):
    """获取用户深度画像"""
    _check_auth()
    try:
        from code.user_profiler import build_deep_profile, get_personalized_strategy
        from code.memory_manager import load_state, get_history
        state = load_state(user_id)
        history = get_history(user_id)
        profile = build_deep_profile(state, history)
        strategies = get_personalized_strategy(profile)
        return jsonify({"profile": profile, "strategies": strategies})
    except Exception as e:
        logger.error(f"获取用户画像失败: {e}")
        return jsonify({"error": "获取失败"}), 500


def _shutdown():
    """优雅关闭调度器"""
    try:
        scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")
    except Exception:
        pass


atexit.register(_shutdown)


if __name__ == '__main__':
    start_scheduler()
    app.run(host='0.0.0.0', port=8080, debug=False)
