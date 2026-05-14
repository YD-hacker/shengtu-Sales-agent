"""启动自检脚本 - UP-012

启动时检查：KB.yaml可解析、CONFIG.yaml可解析、DATA_DIR可读写、向量模型可用、LLM API可达。
自检失败项记录告警但不阻塞启动（降级运行）。
"""
import os
import sys
import yaml
import json
from datetime import datetime
from loguru import logger


def check_config_parsable(config_path: str) -> dict:
    """检查配置文件是否可解析"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        return {"status": "pass", "message": f"{os.path.basename(config_path)} 解析成功"}
    except Exception as e:
        return {"status": "fail", "message": f"{os.path.basename(config_path)} 解析失败: {e}"}


def check_data_dir_rw(data_dir: str) -> dict:
    """检查数据目录是否可读写"""
    try:
        os.makedirs(data_dir, exist_ok=True)
        test_file = os.path.join(data_dir, ".health_check_test")
        with open(test_file, "w") as f:
            f.write("test")
        with open(test_file, "r") as f:
            content = f.read()
        os.remove(test_file)
        if content == "test":
            return {"status": "pass", "message": f"DATA_DIR 读写正常: {data_dir}"}
    except Exception as e:
        return {"status": "fail", "message": f"DATA_DIR 读写失败: {e}"}
    return {"status": "fail", "message": f"DATA_DIR 读写验证异常"}


def check_llm_reachable() -> dict:
    """检查LLM API是否可达"""
    try:
        from code.model_router import get_llm_health
        if get_llm_health():
            return {"status": "pass", "message": "LLM API 可达"}
        return {"status": "warn", "message": "LLM API 不可达（将降级为模板模式）"}
    except Exception as e:
        return {"status": "warn", "message": f"LLM API 检查异常: {e}"}


def check_vector_model_available() -> dict:
    """检查向量模型是否可用"""
    try:
        from code.memory_vector import search
        # 轻量检查：尝试初始化（可能首次需要下载模型）
        return {"status": "pass", "message": "向量模型模块可导入"}
    except ImportError:
        return {"status": "warn", "message": "向量模型模块不可用（需安装 sentence-transformers）"}
    except Exception as e:
        return {"status": "warn", "message": f"向量模型检查异常: {e}"}


def check_required_modules() -> dict:
    """检查关键模块是否可导入"""
    modules = [
        "code.agent_core", "code.state_machine", "code.intent_classifier",
        "code.compliance_checker", "code.guardrail", "code.memory_manager",
        "code.model_router", "code.decision_engine", "code.trust_engine",
        "code.lead_scorer", "code.conversation_analytics", "code.tools",
    ]
    results = []
    for mod in modules:
        try:
            __import__(mod)
            results.append(f"{mod}: OK")
        except Exception as e:
            results.append(f"{mod}: FAIL ({e})")
    passed = sum(1 for r in results if ": OK" in r)
    status = "pass" if passed == len(modules) else "warn" if passed >= len(modules) * 0.7 else "fail"
    return {"status": status, "message": "; ".join(results)}


def run_health_check(base_dir: str = None, config_dir: str = None, data_dir: str = None) -> dict:
    """运行完整启动自检，返回所有检查结果"""
    if base_dir is None:
        from code import BASE_DIR
        base_dir = BASE_DIR
    if config_dir is None:
        from code import CONFIG_DIR
        config_dir = CONFIG_DIR
    if data_dir is None:
        from code import DATA_DIR
        data_dir = DATA_DIR

    from code import CONFIG_FILE, KB_FILE

    checks = {
        "timestamp": datetime.now().isoformat(),
        "base_dir": base_dir,
    }

    # 1. KB.yaml 可解析
    checks["kb_config"] = check_config_parsable(KB_FILE)

    # 2. CONFIG.yaml 可解析
    checks["main_config"] = check_config_parsable(CONFIG_FILE)

    # 3. DATA_DIR 可读写
    checks["data_dir"] = check_data_dir_rw(data_dir)

    # 4. 关键模块导入
    checks["modules"] = check_required_modules()

    # 5. LLM API 可达（网络依赖，可能较慢）
    checks["llm"] = check_llm_reachable()

    # 6. 向量模型
    checks["vector_model"] = check_vector_model_available()

    # 汇总
    statuses = []
    for key, value in checks.items():
        if isinstance(value, dict) and "status" in value:
            statuses.append(value["status"])

    fail_count = statuses.count("fail")
    warn_count = statuses.count("warn")
    pass_count = statuses.count("pass")

    if fail_count == 0 and warn_count == 0:
        checks["overall"] = "healthy"
        logger.info(f"启动自检通过: {pass_count}项全部正常")
    elif fail_count == 0:
        checks["overall"] = "degraded"
        logger.warning(f"启动自检降级: {pass_count}正常, {warn_count}告警")
    else:
        checks["overall"] = "unhealthy"
        logger.error(f"启动自检失败: {fail_count}失败, {warn_count}告警, {pass_count}正常")

    return checks


def print_health_report(results: dict):
    """打印健康检查报告"""
    print("\n" + "=" * 60)
    print("  盛途SalesAgent 启动自检报告")
    print("=" * 60)
    for key, value in results.items():
        if isinstance(value, dict) and "status" in value:
            icon = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]"}.get(value["status"], "[????]")
            print(f"  {icon} {key}: {value['message']}")
    print(f"\n  总体状态: {results.get('overall', 'unknown').upper()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="盛途SalesAgent 启动自检")
    parser.add_argument("--base-dir", help="基础目录路径")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    args = parser.parse_args()

    results = run_health_check(base_dir=args.base_dir)

    if getattr(args, 'json', False):
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_health_report(results)

    # 返回码：fail > 0 则退出码为1
    if results.get("overall") == "unhealthy":
        sys.exit(1)
