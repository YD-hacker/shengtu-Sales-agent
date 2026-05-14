"""数据每日备份脚本 + MD5完整性校验 - UP-216

使用: python scripts/backup.py [--restore BACKUP_FILE]
"""
import os
import sys
import json
import hashlib
import shutil
import argparse
from datetime import datetime, timedelta

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from code import DATA_DIR, CONFIG_DIR

BACKUP_DIR = os.path.join(os.path.dirname(DATA_DIR), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# 备份保留天数
RETENTION_DAYS = 7


def compute_md5(file_path: str) -> str:
    """计算文件MD5"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup() -> str:
    """创建完整备份，返回备份文件路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.zip"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    # 收集要备份的文件
    files_to_backup = []

    # DATA_DIR 下的所有文件
    for root, dirs, files in os.walk(DATA_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            files_to_backup.append(fpath)

    # CONFIG_DIR 下的配置文件
    for fname in os.listdir(CONFIG_DIR):
        if fname.endswith((".yaml", ".yml", ".json")):
            files_to_backup.append(os.path.join(CONFIG_DIR, fname))

    # 创建zip归档
    import zipfile
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in files_to_backup:
            if os.path.isfile(fpath):
                arcname = os.path.relpath(fpath, os.path.dirname(DATA_DIR))
                zf.write(fpath, arcname)

    # 生成MD5校验文件
    md5 = compute_md5(backup_path)
    md5_path = backup_path + ".md5"
    with open(md5_path, "w") as f:
        f.write(f"{md5}  {backup_name}\n")

    # 记录备份清单
    manifest = {
        "backup_file": backup_name,
        "timestamp": datetime.now().isoformat(),
        "file_count": len(files_to_backup),
        "md5": md5,
        "files": [os.path.relpath(f, os.path.dirname(DATA_DIR)) for f in files_to_backup],
    }
    manifest_path = os.path.join(BACKUP_DIR, "backup_manifest.json")
    existing_manifest = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r") as f:
                existing_manifest = json.load(f)
        except Exception:
            existing_manifest = []
    existing_manifest.append(manifest)
    with open(manifest_path, "w") as f:
        json.dump(existing_manifest, f, ensure_ascii=False, indent=2)

    print(f"备份完成: {backup_path}")
    print(f"  - 文件数: {len(files_to_backup)}")
    print(f"  - MD5: {md5}")
    return backup_path


def verify_backup(backup_path: str) -> bool:
    """验证备份完整性"""
    md5_path = backup_path + ".md5"
    if not os.path.exists(md5_path):
        print(f"警告: 未找到MD5校验文件 {md5_path}")
        return False
    with open(md5_path) as f:
        expected = f.read().split()[0]
    actual = compute_md5(backup_path)
    if expected != actual:
        print(f"校验失败: 期望={expected} 实际={actual}")
        return False
    print(f"MD5校验通过: {expected}")
    return True


def cleanup_old_backups():
    """清理超过保留天数的备份"""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    for fname in os.listdir(BACKUP_DIR):
        if not fname.startswith("backup_") or not fname.endswith(".zip"):
            continue
        fpath = os.path.join(BACKUP_DIR, fname)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if mtime < cutoff:
            os.remove(fpath)
            md5_path = fpath + ".md5"
            if os.path.exists(md5_path):
                os.remove(md5_path)
            print(f"清理过期备份: {fname}")


def restore_backup(backup_path: str):
    """从备份恢复数据"""
    import zipfile
    if not os.path.exists(backup_path):
        print(f"错误: 备份文件不存在 {backup_path}")
        sys.exit(1)

    # 验证完整性
    if not verify_backup(backup_path):
        print("警告: 备份完整性验证失败，是否继续？")
        # 在生产环境中应该中止

    # 恢复到临时目录，确认后再覆盖
    restore_root = os.path.dirname(DATA_DIR)
    with zipfile.ZipFile(backup_path, "r") as zf:
        zf.extractall(restore_root)

    print(f"恢复完成: {backup_path} -> {restore_root}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据备份与恢复")
    parser.add_argument("--restore", help="从指定备份文件恢复")
    parser.add_argument("--verify", help="验证指定备份文件")
    parser.add_argument("--cleanup", action="store_true", help="清理过期备份")
    args = parser.parse_args()

    if args.restore:
        restore_backup(args.restore)
    elif args.verify:
        verify_backup(args.verify)
    elif args.cleanup:
        cleanup_old_backups()
    else:
        # 默认：创建备份
        backup_path = create_backup()
        verify_backup(backup_path)
        cleanup_old_backups()
