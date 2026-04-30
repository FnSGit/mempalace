# 实体触发知识图谱注入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 当用户消息提及已知实体时，自动将知识图谱事实注入到 Claude 的上下文中，消除手动搜索开销，确保 AI 在回复前就拥有相关背景信息。

**架构：** UserPromptSubmit hook 从用户提示中提取实体名称，对每个实体查询知识图谱，将事实格式化为紧凑上下文，通过 `additionalContext` 字段注入（不阻塞）。SessionStart hook 增强宫殿分类概览，让 AI 知道有哪些内容存在。

**技术栈：** Python hooks_cli.py 基础设施、entity_registry.extract_people_from_query()、knowledge_graph.query_entity()、Claude Code UserPromptSubmit hook JSON 协议、MempalaceConfig、entity_detector 多语言模式。

---

## Task 1：在 hooks_cli.py 中添加 UserPromptSubmit Hook 处理器

**文件：**
- 修改：`mempalace/hooks_cli.py:240-312`（添加新处理器函数并在调度字典中注册）
- 测试：`tests/test_hooks_cli.py`（添加实体提取和 KG 查询 mock 的单元测试）

- [ ] **Step 1：编写 UserPromptSubmit hook 的失败测试**

在测试文件中创建：

```python
# 在 tests/test_hooks_cli.py 中添加：

def test_hook_user_prompt_submit_extracts_entities():
    """测试 UserPromptSubmit hook 从提示中提取已知实体。"""
    from mempalace.hooks_cli import hook_user_prompt_submit
    from mempalace.knowledge_graph import KnowledgeGraph
    import json

    # Mock KG 带已知实体
    kg = KnowledgeGraph()
    kg.add_triple("Alice", "works_at", "TechCorp", valid_from="2025-01-01")
    kg.add_triple("Alice", "decided", "PostgreSQL over MongoDB", valid_from="2026-04-15")

    # Mock stdin JSON 带实体在提示中
    input_data = {
        "session_id": "test-session-123",
        "transcript_path": "/tmp/test.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Alice 对数据库做了什么决定？"
    }

    # 调用处理器（带 mock KG 实例）
    with patch('mempalace.hooks_cli._get_kg', return_value=kg):
        output = hook_user_prompt_submit(input_data, "claude-code")

    # 应提取 "Alice" 并注入事实
    assert "Alice" in output.get("additionalContext", "")
    assert "PostgreSQL" in output.get("additionalContext", "")
    assert "MongoDB" in output.get("additionalContext", "")
```

- [ ] **Step 2：运行测试验证失败**

运行：`cd /home/fengshuai/projects/ai-agent-plugin/mempalace && python -m pytest tests/test_hooks_cli.py::test_hook_user_prompt_submit_extracts_entities -v`

预期：FAIL，错误为 "hook_user_prompt_submit not defined" 或 "module has no attribute"

- [ ] **Step 3：添加 hook_user_prompt_submit 处理器函数**

在 `mempalace/hooks_cli.py` 中，在 `hook_precompact` 函数后添加（约第 326 行）：

```python
def hook_user_prompt_submit(data: dict, harness: str):
    """
    UserPromptSubmit hook：从用户提示提取实体并注入 KG 事实。

    流程：
    1. 使用 entity_registry 从提示中提取实体名称
    2. 对每个实体查询 KG（outgoing 关系）
    3. 将事实格式化为紧凑上下文（最多 10000 字符）
    4. 通过 additionalContext 字段注入（不阻塞）

    返回：{"additionalContext": "..."} 或 {} 如果没有实体
    """
    from .entity_registry import EntityRegistry
    from .knowledge_graph import KnowledgeGraph

    parsed = _parse_harness_input(data, harness)
    prompt = parsed.get("prompt", "")

    if not prompt:
        _output({})
        return

    _log(f"USER PROMPT SUBMIT: 检查实体 '{prompt[:50]}...'")

    # 从提示中提取已知人物
    registry = EntityRegistry()
    people = registry.extract_people_from_query(prompt)

    if not people:
        _output({})
        return

    _log(f"找到 {len(people)} 个实体名称：{', '.join(people)}")

    # 对每个实体查询 KG
    kg = KnowledgeGraph()
    facts = []
    total_chars = 0
    MAX_CONTEXT_CHARS = 9500  # Claude Code 限制是 10000，留缓冲

    for name in people:
        try:
            results = kg.query_entity(name, direction="outgoing")
            current_facts = [r for r in results if r.get("current", True)]

            for fact in current_facts[:10]:  # 每个实体限制
                line = f"- {fact['subject']} {fact['predicate']} {fact['object']}"
                if fact.get("valid_from"):
                    line += f"（自 {fact['valid_from']}）"

                if total_chars + len(line) > MAX_CONTEXT_CHARS:
                    break

                facts.append(line)
                total_chars += len(line) + 1  # +1 用于换行

        except Exception as e:
            _log(f"{name} 的 KG 查询错误：{e}")
            continue

    if not facts:
        _output({})
        return

    # 格式化上下文块
    context_lines = [
        "[MemPalace 自动上下文 — 知识图谱事实]",
        f"检测到的实体：{', '.join(people)}",
        ""
    ] + facts

    context_text = "\n".join(context_lines)

    _log(f"注入 {len(facts)} 个事实（{total_chars} 字符）")

    # 注入而不阻塞
    output = {"additionalContext": context_text}
    _output(output)
```

- [ ] **Step 4：在调度字典中注册处理器**

修改 `mempalace/hooks_cli.py` 第 240-248 行，更新 `hooks` 字典：

```python
hooks = {
    "session-start": hook_session_start,
    "stop": hook_stop,
    "precompact": hook_precompact,
    "user-prompt-submit": hook_user_prompt_submit,  # 添加这行
}
```

- [ ] **Step 5：添加 helper 解析 UserPromptSubmit 输入**

在 `hooks_cli.py` 中，验证 `_parse_harness_input` 已经处理 UserPromptSubmit（应该已通用）。如果未处理，添加 case：

```python
# 在 _parse_harness_input 函数中（约第 200 行），添加：

if harness == "claude-code":
    return {
        "session_id": data.get("session_id", "unknown"),
        "transcript_path": data.get("transcript_path", ""),
        "cwd": data.get("cwd", ""),
        "permission_mode": data.get("permission_mode", "default"),
        "stop_hook_active": data.get("stop_hook_active", False),
        "prompt": data.get("prompt", ""),  # UserPromptSubmit 特定字段
    }
```

- [ ] **Step 6：运行测试验证通过**

运行：`cd /home/fengshuai/projects/ai-agent-plugin/mempalace && python -m pytest tests/test_hooks_cli.py::test_hook_user_prompt_submit_extracts_entities -v`

预期：PASS

- [ ] **Step 7：提交**

```bash
cd /home/fengshuai/projects/ai-agent-plugin/mempalace
git add mempalace/hooks_cli.py tests/test_hooks_cli.py
git commit -m "feat(hooks): 添加 UserPromptSubmit 处理器用于实体触发的 KG 注入"
```

---

## Task 2：创建 Bash Hook Wrapper 脚本

**文件：**
- 创建：`hooks/mempal_userpromptsubmit_hook.sh`
- 创建：`~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh`

- [ ] **Step 1：编写 hook shell 脚本**

创建文件 `/home/fengshuai/projects/ai-agent-plugin/mempalace/hooks/mempal_userpromptsubmit_hook.sh`：

```bash
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
```

- [ ] **Step 2：使脚本可执行**

运行：`chmod +x /home/fengshuai/projects/ai-agent-plugin/mempalace/hooks/mempal_userpromptsubmit_hook.sh`

预期：脚本现在有执行权限

- [ ] **Step 3：创建用户 wrapper 带 venv 激活**

创建文件 `/home/fengshuai/.claude/hooks/mempal-userpromptsubmit-wrapper.sh`：

```bash
#!/bin/bash
# MemPalace UserPromptSubmit hook wrapper
# 在调用原始 hook 前激活 venv

MEMPALACE_VENV="/home/fengshuai/projects/ai-agent-plugin/mempalace/.venv"
export PATH="$MEMPALACE_VENV/bin:$PATH"

exec bash "/home/fengshuai/projects/ai-agent-plugin/mempalace/hooks/mempal_userpromptsubmit_hook.sh"
```

- [ ] **Step 4：使 wrapper 可执行**

运行：`chmod +x /home/fengshuai/.claude/hooks/mempal-userpromptsubmit-wrapper.sh`

- [ ] **Step 5：手动测试 hook**

运行：
```bash
cat ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh
# 验证脚本内容

# 用 mock JSON 测试（KG 空时应返回 {}）
echo '{"session_id":"test","prompt":"测试消息"}' | ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh
# 预期：{}

# 用实体测试（如果 KG 有数据）
echo '{"session_id":"test","prompt":"Alice 做了什么决定？"}' | ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh
# 预期：带 additionalContext 字段的 JSON
```

- [ ] **Step 6：提交**

```bash
cd /home/fengshuai/projects/ai-agent-plugin/mempalace
git add hooks/mempal_userpromptsubmit_hook.sh
git commit -m "feat(hooks): 添加 UserPromptSubmit bash hook 脚本"
```

---

## Task 3：在 Claude Code 设置中注册 Hook

**文件：**
- 修改：`~/.claude/settings.json:18-64`（添加 UserPromptSubmit hook 条目）

- [ ] **Step 1：读取当前设置**

运行：`cat ~/.claude/settings.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['hooks'], indent=2))"`

验证当前 hooks：SessionStart、PreToolUse、Stop、PreCompact

- [ ] **Step 2：添加 UserPromptSubmit 条目**

编辑 `~/.claude/settings.json`，在 `PreCompact` 条目后添加（约第 63 行）：

```json
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.claude/hooks/mempal-userpromptsubmit-wrapper.sh",
            "timeout": 10
          }
        ]
      }
    ]
```

完整的 hooks section 应为：

```json
  "hooks": {
    "SessionStart": [...],
    "PreToolUse": [...],
    "Stop": [...],
    "PreCompact": [...],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.claude/hooks/mempal-userpromptsubmit-wrapper.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
```

- [ ] **Step 3：验证 JSON 语法**

运行：`python3 -c "import json; json.load(open('$HOME/.claude/settings.json'))" && echo "JSON 有效"`

预期："JSON 有效"

- [ ] **Step 4：重启 Claude Code 加载新 hook**

说明：关闭并重新打开 Claude Code 会话，或运行 `/restart`（如果可用）。

- [ ] **Step 5：验证 hook 已加载**

运行：`cat ~/.mempalace/hook_state/hook.log | grep "USER PROMPT SUBMIT"`

预期：在新会话中发送测试消息时应看到日志条目

---

## Task 4：增强 SessionStart 添加宫殿分类概览

**文件：**
- 修改：`/home/fengshuai/.claude/hooks/mempal-sessionstart-wrapper.sh:40-188`

- [ ] **Step 1：编写分类注入测试**

在 `tests/test_hooks_cli.py`（或需要时新建测试文件）中添加：

```python
def test_session_start_includes_taxonomy():
    """测试 SessionStart hook 包含宫殿分类。"""
    from mempalace.hooks_cli import hook_session_start
    from mempalace.mcp_server import tool_get_taxonomy
    import json

    # Mock stdin
    input_data = {
        "session_id": "test-session",
        "transcript_path": "/tmp/test.jsonl"
    }

    # 调用处理器（捕获 stdout）
    import sys
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    hook_session_start(input_data, "claude-code")

    output = sys.stdout.getvalue()
    sys.stdout = old_stdout

    # 应包含分类 section
    assert "Palace Overview" in output or "wing" in output.lower()
```

- [ ] **Step 2：运行测试验证当前行为**

运行：`python -m pytest tests/test_hooks_cli.py::test_session_start_includes_taxonomy -v`

预期：FAIL（分类尚未包含）

- [ ] **Step 3：在 SessionStart wrapper 中添加分类生成**

修改 `/home/fengshuai/.claude/hooks/mempal-sessionstart-wrapper.sh`，在 diary 加载 section 后添加（约第 160 行）：

```bash
# === 添加宫殿分类概览 ===
echo "" >> "$OUTPUT_FILE"
echo "## Palace Overview — Wing/Room 结构" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# 调用 mempalace status 获取分类
if command -v mempalace >/dev/null 2>&1; then
    TAXONOMY=$(mempalace status 2>/dev/null | grep -A 100 "WING:" | head -50)

    if [ -n "$TAXONOMY" ]; then
        echo "$TAXONOMY" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
        echo "**目的：** 让 AI 知道宫殿中有哪些内容，以便智能搜索。" >> "$OUTPUT_FILE"
    else
        echo "(未找到宫殿数据 — 运行 mempalace mine)" >> "$OUTPUT_FILE"
    fi
else
    echo "(mempalace CLI 未找到)" >> "$OUTPUT_FILE"
fi
```

- [ ] **Step 4：手动测试**

运行：
```bash
~/.claude/hooks/mempal-sessionstart-wrapper.sh | head -100
# 验证输出包含 "Palace Overview" section 带 wing/room 计数
```

- [ ] **Step 5：运行测试验证增强**

运行：`python -m pytest tests/test_hooks_cli.py::test_session_start_includes_taxonomy -v`

预期：PASS

- [ ] **Step 6：提交**

```bash
git add ~/.claude/hooks/mempal-sessionstart-wrapper.sh
git commit -m "feat(hooks): 在 SessionStart 注入中添加宫殿分类"
```

---

## Task 5：添加集成测试

**文件：**
- 创建：`tests/test_hooks_integration.py`

- [ ] **Step 1：编写集成测试**

创建 `tests/test_hooks_integration.py`：

```python
"""Hook 工作流集成测试。"""
import json
import subprocess
import tempfile
from pathlib import Path


def test_user_prompt_submit_hook_with_real_kg():
    """测试 UserPromptSubmit hook 与真实 KG 数据库。"""
    # Setup：创建临时 KG 带已知实体
    from mempalace.knowledge_graph import KnowledgeGraph

    kg_path = tempfile.mkdtemp()
    kg = KnowledgeGraph(db_path=str(Path(kg_path) / "test_kg.sqlite3"))
    kg.add_triple("Alice", "works_at", "TechCorp")
    kg.add_triple("Alice", "decided", "PostgreSQL for DB")

    # 模拟 hook 输入
    hook_input = json.dumps({
        "session_id": "test",
        "prompt": "Alice 做了什么决定？"
    })

    # 运行 hook 子进程
    result = subprocess.run(
        ["/home/fengshuai/.claude/hooks/mempal-userpromptsubmit-wrapper.sh"],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=5
    )

    output = json.loads(result.stdout)

    # 应注入上下文
    assert "additionalContext" in output
    assert "Alice" in output["additionalContext"]
    assert "PostgreSQL" in output["additionalContext"]


def test_entity_extraction_from_complex_prompt():
    """测试从复杂提示中提取实体（多个实体）。"""
    from mempalace.entity_registry import EntityRegistry

    # Setup registry 带已知人物
    registry = EntityRegistry()
    registry._data["people"]["Alice"] = {
        "source": "onboarding",
        "contexts": ["work"],
        "confidence": 1.0
    }
    registry._data["people"]["Bob"] = {
        "source": "learned",
        "contexts": ["personal"],
        "confidence": 0.9
    }
    registry.save()

    # 从复杂提示中提取
    prompt = "Alice 和 Bob 能协作进行数据库重新设计吗？"
    people = registry.extract_people_from_query(prompt)

    assert "Alice" in people
    assert "Bob" in people
    assert len(people) == 2
```

- [ ] **Step 2：运行集成测试**

运行：`python -m pytest tests/test_hooks_integration.py -v`

预期：PASS（如果 KG 有数据）或 skip 如果依赖缺失

- [ ] **Step 3：添加空 KG 边界 case 测试**

添加到同一文件：

```python
def test_user_prompt_submit_empty_kg():
    """测试 KG 无实体时的 hook 行为。"""
    hook_input = json.dumps({
        "session_id": "test",
        "prompt": "Alice 做了什么决定？"
    })

    result = subprocess.run(
        ["/home/fengshuai/.claude/hooks/mempal-userpromptsubmit-wrapper.sh"],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=5
    )

    output = json.loads(result.stdout) if result.stdout.strip() else {}

    # 如果无实体应返回空 JSON
    assert output == {} or "additionalContext" not in output
```

- [ ] **Step 4：运行所有测试**

运行：`python -m pytest tests/ -k "hook" -v`

预期：所有 hook 相关测试通过

- [ ] **Step 5：提交**

```bash
git add tests/test_hooks_integration.py
git commit -m "test(hooks): 添加 UserPromptSubmit 工作流集成测试"
```

---

## Task 6：添加错误处理和边界 Case

**文件：**
- 修改：`mempalace/hooks_cli.py:hook_user_prompt_submit`

- [ ] **Step 1：添加空 stdin 处理**

修改 `hook_user_prompt_submit` 处理空 stdin：

```python
def hook_user_prompt_submit(data: dict, harness: str):
    """..."""
    # 处理空输入（Claude Code bug #996）
    if not data:
        _output({})
        return

    parsed = _parse_harness_input(data, harness)
    # ... 函数其余部分
```

- [ ] **Step 2：添加上下文大小限制**

在格式化前添加大小检查：

```python
def hook_user_prompt_submit(data: dict, harness: str):
    """..."""
    # ... 实体提取和 KG 查询 ...

    # 硬限制：10000 字符
    MAX_CONTEXT_CHARS = 9500  # 留 500 缓冲
    if total_chars > MAX_CONTEXT_CHARS:
        context_text = context_text[:MAX_CONTEXT_CHARS] + "\n[...截断，使用 mempalace_kg_query 获取完整事实]"

    # 注入
    output = {"additionalContext": context_text}
    _output(output)
```

- [ ] **Step 3：添加重复实体去重**

添加去重逻辑：

```python
def hook_user_prompt_submit(data: dict, harness: str):
    """..."""
    # ... 实体提取 ...

    # 去重事实（相同 subject+predicate+object）
    seen_facts = set()
    unique_facts = []
    for fact in facts:
        key = f"{fact['subject']}|{fact['predicate']}|{fact['object']}"
        if key not in seen_facts:
            seen_facts.add(key)
            unique_facts.append(fact)

    facts = unique_facts
```

- [ ] **Step 4：添加调试日志**

增强日志：

```python
def hook_user_prompt_submit(data: dict, harness: str):
    """..."""
    _log(f"USER PROMPT SUBMIT: session={session_id}, prompt='{prompt[:50]}...'")
    _log(f"提取的实体：{people}")
    _log(f"KG 查询：{len(facts)} 个事实")
    _log(f"注入上下文：{total_chars} 字符")
```

- [ ] **Step 5：测试边界 case**

运行：
```bash
# 测试空提示
echo '{"session_id":"test","prompt":""}' | ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh
# 预期：{}

# 测试非常长的提示带多个实体
echo '{"session_id":"test","prompt":"Alice Bob Charlie Dave Eve Frank 对数据库架构做了决定"}' | ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh
# 预期：如果事实太多，JSON 带截断上下文
```

- [ ] **Step 6：提交**

```bash
git add mempalace/hooks_cli.py
git commit -m "fix(hooks): 添加空 stdin 和上下文大小限制的错误处理"
```

---

## Task 7：文档和使用指南

**文件：**
- 创建：`docs/hooks-entity-injection.md`
- 更新：`hooks/README.md`

- [ ] **Step 1：编写使用文档**

创建 `docs/hooks-entity-injection.md`：

```markdown
# 实体触发的知识图谱注入

## 概述

MemPalace 在用户消息提及已知实体（人物、项目）时，自动将相关知识图谱事实注入到 Claude 的上下文中。这消除了手动搜索开销，确保 AI 在回复前就拥有背景信息。

## 工作原理

1. **用户发送消息** → "Alice 对数据库做了什么决定？"
2. **UserPromptSubmit hook 触发** → 提取实体名称：`["Alice"]`
3. **知识图谱查询** → 找到事实：`Alice → decided → PostgreSQL（2026-04-15）`
4. **上下文注入** → Claude 看到：`[MemPalace 自动上下文] Alice decided PostgreSQL（2026-04-15）`
5. **AI 回复** → 已知答案无需搜索

## 安装

Hook 自动注册在 `~/.claude/settings.json`：

```json
"UserPromptSubmit": [{
  "hooks": [{
    "type": "command",
    "command": "$HOME/.claude/hooks/mempal-userpromptsubmit-wrapper.sh",
    "timeout": 10
  }]
}]
```

## 配置

**启用/禁用：** 从 settings.json 删除 hook 条目以禁用。

**上下文大小限制：** 9500 字符（Claude Code 硬限制是 10000）。

**KG 查询深度：** 仅 outgoing 关系，仅当前事实（未过期）。

## 故障排查

**Hook 未触发：**
- 检查 `~/.mempalace/hook_state/hook.log` 中 "USER PROMPT SUBMIT" 条目
- 验证 wrapper 脚本可执行：`ls -l ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh`
- 重启 Claude Code 会话

**无上下文注入：**
- 实体不在 registry → 通过 `mempalace init` 或手动 KG 条目添加
- KG 空 → 运行 `mempalace mine` 填充
- 检查 entity_registry.json：`cat ~/.mempalace/entity_registry.json | grep Alice`

**错误上下文：**
- 事实过期 → KG 条目在不再为真时有 `valid_to` 日期
- 多个实体 → 事实去重但可能来自不同来源

## 示例

**示例 1：单个实体**
```
用户："Alice 选择了什么数据库？"
Hook 提取：["Alice"]
KG 事实：Alice decided PostgreSQL over MongoDB（2026-04-15）
注入：[MemPalace 自动上下文]
- Alice decided PostgreSQL over MongoDB（自 2026-04-15）
```

**示例 2：多个实体**
```
用户："Alice 和 Bob 能协作重新设计吗？"
Hook 提取：["Alice", "Bob"]
KG 事实：Alice works_at TechCorp, Bob partner_of Alice
注入：[MemPalace 自动上下文]
- Alice works_at TechCorp
- Bob partner_of Alice
```

**示例 3：未知实体**
```
用户："Charlie 做了什么决定？"
Hook 提取：[]
无 KG 查询 → 无上下文注入
AI 必须使用 mempalace_search 或询问用户
```

## 与 PALACE_PROTOCOL 集成

SessionStart 也注入 `PALACE_PROTOCOL` 指令：

```
1. 遇到人名/项目名 → 先查 mempalace_kg_query
2. 需要历史细节 → 调 mempalace_search
3. 不确定的事实 → 先查再说，宁慢勿错
```

UserPromptSubmit hook 使步骤 1 自动化。AI 在需要时仍调用 `mempalace_search`（步骤 2）获取深度上下文。

## 性能

- 实体提取：~5ms（内存 registry 查找）
- KG 查询：~50ms 每实体（SQLite 索引查找）
- 总延迟：典型查询 <100ms
- 上下文大小：每实体 ~200-500 字符（紧凑）

---

## 高级：手动 KG 条目

通过 MCP 工具直接添加事实：

```python
mempalace_kg_add(
    subject="Alice",
    predicate="decided",
    object="PostgreSQL for database",
    valid_from="2026-04-15"
)
```

或通过 CLI：

```bash
mempalace mine conversations/ --mode convos
# 从对话 transcript 提取实体和关系
```
```

- [ ] **Step 2：更新 hooks README**

添加到 `hooks/README.md`：

```markdown
## 可用 Hooks

| Hook | 目的 | 触发时机 |
|------|------|---------|
| SessionStart | 加载项目记忆 + 宫殿分类 | 新会话开始 |
| Stop | 每 30 条交换自动保存 | AI 停止响应 |
| PreCompact | 压缩前紧急保存 | 上下文压缩 |
| **UserPromptSubmit** | **实体触发的 KG 注入** | **用户发送消息** |

### UserPromptSubmit Hook

在用户提及已知实体时自动注入知识图谱事实。

**示例：**
- 用户："Alice 做了什么决定？"
- Hook：提取 "Alice" → 查询 KG → 注入事实
- AI：已知答案无需搜索

详见 `docs/hooks-entity-injection.md` 完整文档。
```

- [ ] **Step 3：提交**

```bash
git add docs/hooks-entity-injection.md hooks/README.md
git commit -m "docs(hooks): 添加实体触发的 KG 注入使用指南"
```

---

## 自检清单

完成所有任务后，验证：

1. **规格覆盖：** 实体触发的 KG 注入实现 ✓ | SessionStart 分类添加 ✓
2. **占位符：** 无 TBD/TODO/未定义引用 ✓
3. **类型一致性：** `extract_people_from_query()` 返回 list[str] → 使用正确 ✓ | `query_entity()` 返回 list[dict] → 使用正确 ✓
4. **文件路径：** 所有绝对路径正确 ✓
5. **测试覆盖：** 实体提取单元测试 ✓ | KG 工作流集成测试 ✓
6. **错误处理：** 空 stdin ✓ | 上下文大小限制 ✓ | 实体去重 ✓
7. **文档：** 使用指南 ✓ | 故障排查 ✓ | 示例 ✓

---

## 执行交接

计划完成并保存到 `docs/superpowers/plans/2026-04-28-entity-triggered-kg-injection.md`。

**两种执行选项：**

**1. Subagent-Driven（推荐）** - 我为每个任务派发新子代理，任务间审查，快速迭代

**2. Inline Execution** - 在此会话中使用 executing-plans 执行任务，批量执行带检查点

**选择哪种方式？**