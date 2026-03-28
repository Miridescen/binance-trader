"""一次性脚本：删除 3/28 误写入的多单记录"""
import db

deleted = db.delete_open_log(
    "open_time LIKE ? AND side = ?",
    ("2026-03-28%", "多")
)
print(f"已删除 {deleted} 条 3/28 多单脏数据")
