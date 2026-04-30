# MemPalace Backend切换说明

## 当前状态（2026-04-26）

**Backend：** Qdrant（默认）
- 代码位置：palace.py:12,44
- 数据库：`~/.mempalace/palace/qdrant/`（940MB）
- 队列：自动集成（QueuedCollection）

**ChromaDB：** 残留未清理
- 数据库：`~/.mempalace/palace/chroma.sqlite3`（307KB）
- 状态：不再使用，可删除

## 为什么删除mempalace-safe-operations skill

**过时原因：**

### 1. Backend切换（ChromaDB → Qdrant）

**之前（ChromaDB）：**
- ❌ HNSW索引损坏 → segfault崩溃
- ❌ SQLite并发写入 → database is locked
- ❌ 索引漂移 → TB级稀疏文件
- ❌ 需要手动检查并发、停止进程

**现在（Qdrant）：**
- ✅ HTTP API自动处理并发
- ✅ Server管理数据库级锁
- ✅ 无segfault问题（纯Rust实现）
- ✅ 无需用户手动管理并发

### 2. 队列自动集成

**palace.py架构：**
```python
# 默认backend
_DEFAULT_BACKEND = QdrantBackend()

# 所有collection返回QueuedCollection（自动队列化）
def get_collection(...):
    raw_collection = _DEFAULT_BACKEND.get_collection(...)
    return QueuedCollection(raw_collection)  # 自动队列化
```

**效果：**
- 所有写入操作自动队列化
- 跨进程严格FIFO顺序
- 用户无需手动检查并发
- 无需停止MCP server或其他进程

### 3. Skill描述的问题已不存在

| 问题 | ChromaDB | Qdrant |
|------|----------|--------|
| Segfault崩溃 | ❌ 常见（HNSW损坏） | ✅ 无此问题 |
| Database locked | ❌ SQLite并发写入 | ✅ HTTP API自动处理 |
| HNSW索引漂移 | ❌ seek position漂移 | ✅ Server管理 |
| TB级稀疏文件 | ❌ resize触发 | ✅ 无此问题 |
| 手动检查并发 | ❌ 必须检查 | ✅ 自动处理 |
| 需要停止进程 | ❌ MCP/CLI冲突 | ✅ 队列自动协调 |

## 当前安全机制

### Qdrant Server优势

**文档（queue.py:1-12）：**
> "Qdrant Server handles its own concurrency (HTTP API is thread-safe).
> This queue is now an **application-level coordinator** that provides:
> - Cross-process FIFO ordering across multiple Claude Code instances
> - Durable write requests (survive crashes / restarts)
> - Automatic retry with exponential backoff
> - Duplicate suppression via atomic claim
> 
> No fcntl locks needed — Qdrant Server manages database-level locking."

**实际效果：**
1. 多个Claude Code实例同时运行 ✓ 安全
2. MCP server + CLI同时写入 ✓ 安全
3. 进程崩溃恢复 ✓ 自动重试
4. 跨进程FIFO顺序 ✓ 保证

### 队列工作流程

```
写入请求 → enqueue_request()
↓
创建JSON文件（纳秒级时序）
↓
process_queue()后台处理
↓
原子claim（rename .json → .processing）
↓
执行operation
↓
成功：删除.processing
失败：重试3次或移入failed目录
```

**用户完全无感知：**
- 不需要手动检查队列状态
- 不需要手动停止进程
- 不需要担心并发写入
- 所有操作自动安全处理

## 队列查询工具（可选）

如果好奇想查看队列状态，可以用这些命令：

### 查看队列状态
```bash
python -c "
import sys
sys.path.insert(0, '/home/fengshuai/projects/ai-agent-plugin/mempalace')
from mempalace.queue import QUEUE_DIR, get_next_request
from pathlib import Path

pending = len(list(QUEUE_DIR.glob('*.json')))
failed_dir = QUEUE_DIR / 'failed'
failed = len(list(failed_dir.glob('*.json'))) if failed_dir.exists() else 0

print(f'待处理: {pending}')
print(f'失败: {failed}')
"
```

### 清空失败请求
```bash
rm -rf ~/.mempalace/queue/failed/*.json
```

**但实际上不需要：**
- 队列自动处理，用户无需关心
- 失败请求自动重试3次
- 真正失败的很少（Qdrant很稳定）

## 清理建议

**可以删除残留ChromaDB数据：**
```bash
# 检查是否还有ChromaDB数据
ls -lh ~/.mempalace/palace/chroma.sqlite3

# 如果确认不用，删除
rm ~/.mempalace/palace/chroma.sqlite3
rm -rf ~/.mempalace/palace/*/link_lists.bin
rm -rf ~/.mempalace/palace/*/data_level0.bin
```

**效果：**
- 释放约307KB空间
- 清理残留文件
- 避免混淆（明确使用Qdrant）

## 总结

**删除mempalace-safe-operations skill的原因：**
1. ✅ Backend已切换到Qdrant（更安全）
2. ✅ 队列自动集成（用户无需手动操作）
3. ✅ Skill描述的ChromaDB问题已不存在
4. ✅ 用户不需要手动检查并发或停止进程

**当前架构优势：**
- Qdrant HTTP API：自动并发处理
- QueuedCollection：自动队列化写入
- 纳秒级FIFO：跨进程严格顺序
- 自动重试：崩溃恢复机制

**用户体验：**
- 完全无感知的安全机制
- 多实例同时运行无冲突
- 无需担心数据损坏
- 无需手动管理队列

---
*说明创建于 2026-04-26。原因：删除过时的mempalace-safe-operations skill，Backend已切换到Qdrant，队列自动集成。*