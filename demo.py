#!/usr/bin/env python3
"""
盛途Sales Agent 交互式演示脚本

用法：
    python demo.py [--server SERVER_URL] [--token API_TOKEN]

功能：
    1. 健康检查
    2. 交互式对话（模拟真实用户）
    3. 预设场景演示
    4. 用户画像查询
    5. 线索评分查询
"""
import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    sys.exit(1)


DEFAULT_SERVER = "http://localhost:8080"
DEFAULT_TOKEN = "your-api-token-here"


class SalesAgentDemo:
    def __init__(self, server: str, token: str):
        self.server = server.rstrip("/")
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

    def health_check(self) -> dict:
        """健康检查"""
        try:
            resp = requests.get(f"{self.server}/health", timeout=10)
            return resp.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def chat(self, user_id: str, msg: str) -> str:
        """发送消息并获取流式回复"""
        try:
            resp = requests.post(
                f"{self.server}/test/chat",
                headers=self.headers,
                json={"user_id": user_id, "msg": msg, "stream": True},
                timeout=60,
                stream=True
            )
            reply = ""
            for line in resp.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    reply += data
            return reply
        except Exception as e:
            return f"[错误: {e}]"

    def get_user_score(self, user_id: str) -> dict:
        """查询用户线索分"""
        try:
            resp = requests.get(
                f"{self.server}/api/user/{user_id}/score",
                headers=self.headers,
                timeout=10
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def get_user_profile(self, user_id: str) -> dict:
        """查询用户画像"""
        try:
            resp = requests.get(
                f"{self.server}/api/user/{user_id}/profile",
                headers=self.headers,
                timeout=10
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_agent_reply(reply: str):
    print(f"\n  小范: {reply}")
    print()


def run_health_check(demo: SalesAgentDemo):
    """运行健康检查"""
    print_header("健康检查")
    health = demo.health_check()
    if health.get("status") == "ok":
        print(f"  状态: {health['status']}")
        print(f"  LLM: {health.get('llm', 'unknown')}")
        print(f"  存储: {health.get('storage', 'unknown')}")
        print(f"  调度器: {health.get('scheduler', 'unknown')}")
        print(f"  用户数: {health.get('user_count', 0)}")
        print(f"  版本: {health.get('version', 'unknown')}")
    else:
        print(f"  状态异常: {health}")


def run_interactive_chat(demo: SalesAgentDemo):
    """交互式对话"""
    print_header("交互式对话")
    print("  输入消息与Agent对话，输入 'quit' 退出")
    print("  输入 '/score' 查看线索分，'/profile' 查看画像")
    print()

    user_id = f"demo_{int(time.time())}"
    print(f"  用户ID: {user_id}")
    print()

    while True:
        try:
            msg = input("  你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  退出对话")
            break

        if not msg:
            continue
        if msg.lower() == "quit":
            print("  退出对话")
            break
        if msg == "/score":
            score = demo.get_user_score(user_id)
            print(f"\n  线索分: {json.dumps(score, ensure_ascii=False, indent=4)}")
            continue
        if msg == "/profile":
            profile = demo.get_user_profile(user_id)
            print(f"\n  用户画像: {json.dumps(profile, ensure_ascii=False, indent=4)}")
            continue

        reply = demo.chat(user_id, msg)
        print_agent_reply(reply)


def run_preset_scenarios(demo: SalesAgentDemo):
    """预设场景演示"""
    print_header("预设场景演示")

    scenarios = [
        {
            "name": "场景1：正常咨询流程",
            "user_id": "demo_normal",
            "messages": [
                "你好",
                "我是大专毕业，在广州，25岁",
                "2022年毕业的，想学网安",
                "多少钱啊",
                "好的，什么时候可以去看看",
            ]
        },
        {
            "name": "场景2：异议处理",
            "user_id": "demo_objection",
            "messages": [
                "你好",
                "本科，28岁，深圳",
                "2020年毕业，大数据方向",
                "我再想想吧",
                "太贵了，能不能便宜点",
                "太远了不方便过去",
            ]
        },
        {
            "name": "场景3：辱骂处理",
            "user_id": "demo_insult",
            "messages": [
                "你好",
                "滚蛋，骗子",
            ]
        },
        {
            "name": "场景4：信息纠正",
            "user_id": "demo_correct",
            "messages": [
                "你好",
                "我是本科，25岁，广州",
                "不对，我说错了，我是大专",
                "2023年毕业的，想学网安",
            ]
        },
    ]

    for scenario in scenarios:
        print(f"\n  --- {scenario['name']} ---")
        user_id = scenario["user_id"]
        for msg in scenario["messages"]:
            print(f"\n  你: {msg}")
            reply = demo.chat(user_id, msg)
            print_agent_reply(reply)
            time.sleep(0.5)  # 模拟真实对话节奏

        # 查询最终状态
        score = demo.get_user_score(user_id)
        if "error" not in score:
            print(f"  [线索分: {score.get('lead_score', '?')}, "
                  f"等级: {score.get('lead_grade', '?')}, "
                  f"阶段: {score.get('current_node', '?')}]")
        print()


def main():
    parser = argparse.ArgumentParser(description="盛途Sales Agent 演示脚本")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="服务器地址")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="API Token")
    parser.add_argument("--mode", choices=["health", "chat", "scenario", "all"],
                        default="all", help="演示模式")
    args = parser.parse_args()

    demo = SalesAgentDemo(args.server, args.token)

    print_header("盛途Sales Agent 演示")
    print(f"  服务器: {args.server}")
    print(f"  Token: {args.token[:20]}...")

    if args.mode in ("health", "all"):
        run_health_check(demo)

    if args.mode in ("scenario", "all"):
        run_preset_scenarios(demo)

    if args.mode in ("chat", "all"):
        run_interactive_chat(demo)


if __name__ == "__main__":
    main()
