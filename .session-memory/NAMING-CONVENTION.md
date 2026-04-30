# Session Diary 文件命名规范

## 命名格式

**标准格式：** `.session-diary-YYYY-MM-DD-HHMM-topic.md`

**示例：**
```
.session-diary-2026-04-26-1918-intelligent-loading-complete.md
.session-diary-2026-04-26-1915-intelligent-loading-optimization.md
.session-diary-2026-04-26-1904-sessionstart-implementation.md
```

## 格式说明

- **YYYY-MM-DD：** 年月日（如 2026-04-26）
- **HHMM：** 时分（24小时制，如 1918 = 19:18）
- **topic：** 本次会话的主题关键词（简短描述）
- **不用冒号：** 避免某些系统的兼容性问题

## 时间来源

**精确时间获取：**
```bash
# 获取当前时间（时分）
TIMESTAMP=$(date '+%Y-%m-%d-%H%M')

# 或从文件修改时间获取
FILE_TIME=$(stat -c '%y' "$file" | cut -d'.' -f1 | sed 's/[: -]//g' | cut -c1-15)
# 2026-04-26 19:18:47 → 20260426-1918
```

## 排序优势

**之前（只有年月日）：**
```
.session-diary-2026-04-26-intelligent-loading-complete.md
.session-diary-2026-04-26-intelligent-loading-optimization.md
.session-diary-2026-04-26-sessionstart-implementation.md
```
问题：同一天多个文件，按字母排序，时间顺序不明显 ✓

**现在（精确时分）：**
```
.session-diary-2026-04-26-1918-intelligent-loading-complete.md  (19:18)
.session-diary-2026-04-26-1915-intelligent-loading-optimization.md (19:15)
.session-diary-2026-04-26-1904-sessionstart-implementation.md (19:04)
```
优势：按文件名排序 = 按时间排序，一目了然 ✓

## 时间精度

**精确到分钟：**
- 同一小时内多次会话可以区分
- 文件名不会过长（HHMM只占4字符）
- 足够精确，不需要秒数

## 命名时机

**AI写日记时：**
```bash
# 获取当前时间
CURRENT_TIME=$(date '+%Y-%m-%d-%H%M')

# 创建文件名（AI使用）
FILE_NAME=".session-diary-${CURRENT_TIME}-topic.md"
```

**Wrapper移动文件时（可选重命名）：**
如果原文件名缺少时分，wrapper可以自动重命名：
```bash
# 获取文件修改时间
FILE_TIME=$(stat -c '%y' "$file" | awk '{print $1"-"$2}' | cut -c1-16 | sed 's/:/')

# 重命名
NEW_NAME=".session-diary-${FILE_TIME}-topic.md"
mv "$file" "$NEW_NAME"
```

## 批量重命名脚本

**重命名现有文件：**
```bash
cd .claude/session-memory/

for file in .session-diary-2026-04-26-*.md; do
    # 获取修改时间（2026-04-26 19:18:47）
    MTIME=$(stat -c '%y' "$file")
    
    # 提取时分（19:18 → 1918）
    HHMM=$(echo "$MTIME" | cut -d' ' -f2 | cut -c1-5 | sed 's/:/')
    
    # 提取主题（去除日期部分）
    TOPIC=$(basename "$file" | sed 's/.session-diary-2026-04-26-/topic-/' | sed 's/.md//')
    
    # 新文件名
    NEW=".session-diary-2026-04-26-${HHMM}-${TOPIC}.md"
    
    # 重命名
    mv "$file" "$NEW"
    echo "Renamed: $file → $NEW"
done
```

## 用户建议（verbatim）

**用户提出：** "现在文件只显示年月日，加上时分秒更方便排序和查看"

**改进效果：**
- 文件名包含精确时间（时分）
- 按文件名排序 = 按时间排序
- 一目了然，无需查看文件属性 ✓

## 下次会话实施

**AI命名规范：**
从下次日记开始，AI自觉使用格式：
`.session-diary-YYYY-MM-DD-HHMM-topic.md`

**示例：**
```
下次会话时间：19:30
主题：测试智能加载效果
文件名：.session-diary-2026-04-26-1930-test-intelligent-loading.md
```

---
*命名规范创建于 2026-04-26 19:18。用户建议：加上时分方便排序和查看。*