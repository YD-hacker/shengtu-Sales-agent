
import re

# Read the file
with open("/opt/ai-agent/code/state_machine.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: show_fee + fee_intent -> invite
old1 = """    elif current_state == "show_fee":
        if intent == "confirm":
            target_state = "invite"
        elif intent.startswith("objection_") or intent == "fee_intent":
            target_state = "show_fee"
        else:
            target_state = "show_fee" """

new1 = """    elif current_state == "show_fee":
        if intent in ("confirm", "fee_intent"):
            target_state = "invite"
        elif intent.startswith("objection_"):
            target_state = "show_fee"
        else:
            target_state = "show_fee" """

content = content.replace(old1.strip(), new1.strip())

# Fix 2: qualify opening includes "小苏"
old2 = 'return "我之前也是做技术的，后来转做IT人才服务6年了。讲真的，转行是个大事儿，我先了解下你的情况——学历是统招大专还是本科？哪年毕业？多大了？在哪个城市？"'
new2 = 'return "你好呀，我是小苏，做IT人才服务6年了。讲真的，转行是个大事儿，我先了解下你的情况——学历是统招大专还是本科？哪年毕业？多大了？在哪个城市？"'

content = content.replace(old2, new2)

# Write back
with open("/opt/ai-agent/code/state_machine.py", "w", encoding="utf-8") as f:
    f.write(content)

# Verify
with open("/opt/ai-agent/code/state_machine.py", "r", encoding="utf-8") as f:
    verify = f.read()

# Check fix 1
if 'if intent in ("confirm", "fee_intent"):' in verify:
    print("Fix 1 VERIFIED: show_fee + fee_intent -> invite")
else:
    print("Fix 1 FAILED")

# Check fix 2
if "我是小苏" in verify:
    print("Fix 2 VERIFIED: qualify opening includes 小苏")
else:
    print("Fix 2 FAILED")
    # Debug
    for i, line in enumerate(verify.split("
")):
        if "转行是个大事儿" in line:
            print(f"  Debug line {i}: {repr(line)}")
