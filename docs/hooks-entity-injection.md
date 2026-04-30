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

Hook 通过 wrapper 脚本自动管理 venv 环境。配置已自动添加到 `~/.claude/settings.json`。

**手动配置（可选）：**
如需手动配置，在 `~/.claude/settings.json` 的 `hooks` 部分添加：

```json
"UserPromptSubmit": [{
  "hooks": [{
    "type": "command",
    "command": "$HOME/.claude/hooks/mempal-userpromptsubmit-wrapper.sh",
    "timeout": 10
  }]
}]
```

**Wrapper 脚本作用：**
wrapper 脚本激活 mempalace venv 环境，确保 Python 依赖可用。

## 配置

**启用/禁用：** 手动编辑 `~/.claude/settings.json`，移除 `UserPromptSubmit` 配置块即可禁用。

**上下文大小限制：** 9500 字符（Claude Code 硬限制是 10000）。

**KG 查询深度：** 仅 outgoing 关系，仅当前事实（未过期）。

## 故障排查

**Hook 未触发：**
- 检查 `~/.mempalace/hook_state/hook.log` 中 "USER PROMPT SUBMIT" 条目
- 验证 wrapper 脚本可执行：`ls -l ~/.claude/hooks/mempal-userpromptsubmit-wrapper.sh`
- 验证 settings.json 配置：`cat ~/.claude/settings.json | grep UserPromptSubmit`
- 重启 Claude Code 会话（hooks 在会话启动时加载）

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