#!/bin/bash
# MemPalace UserPromptSubmit Hook — 实体触发的知识图谱注入
#
# Claude Code 在用户提交提示时触发此 hook。
# 我们提取实体名称，查询 KG，并将事实注入为上下文。
#
# === 安装 ===
# 添加到 .claude/settings.json：
#
#   "hooks": {
#     "UserPromptSubmit": [{
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_userpromptsubmit_hook.sh",
#         "timeout": 10
#       }]
#     }]
#   }

# 解析 Python 解释器
MEMPAL_PYTHON_BIN="${MEMPAL_PYTHON:-}"
if [ -z "$MEMPAL_PYTHON_BIN" ] || [ ! -x "$MEMPAL_PYTHON_BIN" ]; then
    MEMPAL_PYTHON_BIN="$(command -v python3 2>/dev/null || echo python3)"
fi

# 从 stdin 读取 JSON
INPUT=$(cat)

# 调用 Python hook 处理器
echo "$INPUT" | "$MEMPAL_PYTHON_BIN" -m mempalace.hooks_cli run --hook user-prompt-submit --harness claude-code
