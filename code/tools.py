"""工具调用模块 - 让LLM能"做事"

功能：
1. 定义可用工具
2. 执行工具调用（含超时控制）
3. 工具结果格式化
4. 工具结果同轮缓存
"""
import json
import time
import threading
from loguru import logger

# UP-008: 工具执行超时（秒）
TOOL_EXEC_TIMEOUT = 10

# UP-107: 工具结果同轮缓存（5秒内同一工具+同一参数返回缓存）
_tool_cache = {}
_tool_cache_lock = threading.Lock()
_TOOL_CACHE_TTL = 5  # 秒

# 可用工具定义
TOOLS = [
    {
        "name": "query_user_info",
        "description": "查询用户已收集的信息（学历、年龄、城市、方向等）",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID"}
            },
            "required": ["user_id"]
        }
    },
    {
        "name": "check_qualification",
        "description": "检查用户是否符合保障班资格（需要统招大专及以上学历，年龄18-32岁）",
        "parameters": {
            "type": "object",
            "properties": {
                "education": {"type": "string", "description": "用户学历"},
                "age": {"type": "string", "description": "用户年龄"}
            },
            "required": ["education", "age"]
        }
    },
    {
        "name": "match_campus",
        "description": "根据用户城市和方向匹配最近的校区",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "用户所在城市"},
                "direction": {"type": "string", "description": "学习方向：网安或大数据"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "get_case",
        "description": "获取与用户情况最匹配的学员成功案例",
        "parameters": {
            "type": "object",
            "properties": {
                "pain_type": {"type": "string", "description": "痛点类型：age_too_old/factory_worker/low_end_job/layoff等"},
                "age": {"type": "string", "description": "用户年龄"},
                "education": {"type": "string", "description": "用户学历"}
            }
        }
    },
    {
        "name": "get_lead_info",
        "description": "获取用户的线索评分和等级信息",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID"}
            },
            "required": ["user_id"]
        }
    }
]


def execute_tool(tool_name, parameters, user_id=None, timeout=TOOL_EXEC_TIMEOUT):
    """执行工具调用（带超时控制和同轮缓存）"""
    # UP-107: 同轮缓存检查
    cache_key = f"{tool_name}:{json.dumps(parameters, sort_keys=True)}:{user_id}"
    with _tool_cache_lock:
        cached = _tool_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < _TOOL_CACHE_TTL:
            logger.info(f"工具缓存命中: {tool_name}")
            return cached["result"]

    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_execute_tool_inner, tool_name, parameters, user_id)
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.warning(f"工具执行超时 {tool_name} (>{timeout}s)")
                return {"error": f"工具执行超时（>{timeout}秒）"}

        # UP-107: 缓存结果
        with _tool_cache_lock:
            _tool_cache[cache_key] = {"result": result, "ts": time.time()}
        return result
    except Exception as e:
        logger.error(f"工具执行失败 {tool_name}: {e}")
        return {"error": str(e)}


def _execute_tool_inner(tool_name, parameters, user_id):
    """工具调用内部实现"""
    if tool_name == "query_user_info":
        return _query_user_info(parameters.get("user_id", user_id))
    elif tool_name == "check_qualification":
        return _check_qualification(parameters)
    elif tool_name == "match_campus":
        return _match_campus(parameters)
    elif tool_name == "get_case":
        return _get_case(parameters)
    elif tool_name == "get_lead_info":
        return _get_lead_info(parameters.get("user_id", user_id))
    else:
        return {"error": f"未知工具: {tool_name}"}


def _query_user_info(uid):
    """查询用户信息"""
    if not uid:
        return {"error": "缺少user_id"}
    from code.memory_manager import load_state
    state = load_state(uid)
    fields = ["education", "age", "city", "direction", "graduated_year",
              "name", "phone", "current_node", "trust_level", "lead_score"]
    return {k: state.get(k) for k in fields if state.get(k)}


def _check_qualification(params):
    """检查保障班资格"""
    from code.state_machine import check_qualification
    qualified = check_qualification({
        "education": params.get("education", ""),
        "age": params.get("age", ""),
        "major": params.get("major", ""),
        "graduated_year": params.get("graduated_year", ""),
        "direction": params.get("direction", ""),
    })
    result = {"qualified": qualified}
    if not qualified:
        result["reason"] = "保障班要求统招大专及以上学历，年龄18-32岁"
        result["alternative"] = "可以考虑非保障技能班，费用1万4左右"
    return result


def _match_campus(params):
    """匹配校区"""
    city = params.get("city", "")
    direction = params.get("direction", "网安")

    campus_map = {
        "广州": "广州校区", "深圳": "广州校区", "东莞": "广州校区",
        "佛山": "广州校区", "惠州": "广州校区", "赣州": "广州校区",
        "杭州": "杭州校区", "宁波": "杭州校区", "上海": "杭州校区",
        "南京": "杭州校区", "苏州": "杭州校区", "合肥": "杭州校区",
    }

    matched = None
    for key, campus in campus_map.items():
        if key in city:
            matched = campus
            break

    if not matched:
        matched = "广州校区（推荐）"

    return {
        "campus": matched,
        "direction": direction,
        "accommodation": "免费住宿",
        "note": f"离你最近的是{matched}，{direction}方向有对应课程"
    }


def _get_case(params):
    """获取匹配案例"""
    from code.content_generator import match_case, format_case_for_prompt
    case = match_case(params)
    if case:
        return {
            "found": True,
            "case": format_case_for_prompt(case)
        }
    return {
        "found": False,
        "default_case": "上个月有个30岁零基础的学员，一个半月学完现在在网安岗位月薪9000+"
    }


def _get_lead_info(uid):
    """获取线索信息"""
    if not uid:
        return {"error": "缺少user_id"}
    from code.memory_manager import load_state
    from code.lead_scorer import calculate_lead_score, get_lead_grade, get_lead_strategy
    state = load_state(uid)
    score = calculate_lead_score(state)
    grade = get_lead_grade(score)
    strategy = get_lead_strategy(score)
    return {
        "lead_score": score,
        "lead_grade": grade,
        "strategy": strategy,
        "trust_level": state.get("trust_level", 50),
        "current_node": state.get("current_node", "icebreak")
    }


def build_tool_prompt(user_msg, state, available_tools=None):
    """构建工具调用决策prompt"""
    if available_tools is None:
        available_tools = TOOLS

    tools_desc = "\n".join([
        f"- {t['name']}: {t['description']}" for t in available_tools
    ])

    uid = state.get("_user_id", "")
    current_info = {k: state.get(k) for k in
                    ["education", "age", "city", "direction", "graduated_year"]
                    if state.get(k)}
    info_str = json.dumps(current_info, ensure_ascii=False) if current_info else "无"

    prompt = f"""你是小范的AI助手。用户说："{user_msg}"

当前已知信息：{info_str}

可用工具：
{tools_desc}

判断是否需要调用工具来更好地回复用户。
如果需要，输出JSON：{{"tool": "工具名", "parameters": {{...}}}}
如果不需要调用工具，直接回复用户即可。"""

    return prompt
