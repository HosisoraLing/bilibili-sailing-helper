#!/usr/bin/env python3
"""
数据修复脚本：修正因缓存串号导致的昵称污染

用法:
    python scripts/repair_nicknames.py --dry-run    # 只打印差异清单（默认）
    python scripts/repair_nicknames.py --apply       # 写库前自动备份 SQLite 到 backups/
"""
import argparse
import os
import sys
import shutil
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from db.models import db, Guard, Address, User, get_beijing_now


def get_db_path():
    """获取数据库文件路径"""
    db_url = Config.SQLALCHEMY_DATABASE_URI
    if db_url.startswith('sqlite:///'):
        return db_url.replace('sqlite:///', '')
    return None


def backup_database(db_path):
    """备份数据库到 backups/ 目录"""
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(db_path)), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(backup_dir, f'data-{timestamp}.db')
    
    shutil.copy2(db_path, backup_path)
    print(f"✓ 数据库已备份到: {backup_path}")
    return backup_path


def find_nickname_discrepancies():
    """
    查找昵称不一致的记录
    
    以 Guard 表为准，比对：
    1. Address.nickname 与 Guard.nickname
    2. User.nickname 与 Guard.nickname（仅修 uid 存在于 guards 表的记录）
    
    管理员用户名格式 "管理员_{uid}" 不动
    """
    discrepancies = []
    
    # 获取所有 Guard 记录
    guards = {g.uid: g for g in Guard.query.all()}
    
    # 检查 Address 表
    addresses = Address.query.all()
    for addr in addresses:
        if addr.uid in guards:
            guard = guards[addr.uid]
            if addr.nickname != guard.nickname:
                discrepancies.append({
                    'table': 'Address',
                    'uid': addr.uid,
                    'current': addr.nickname,
                    'correct': guard.nickname,
                    'record_id': addr.id
                })
    
    # 检查 User 表
    users = User.query.all()
    for user in users:
        # 跳过管理员（格式为 "管理员_{uid}"）
        if user.nickname and user.nickname.startswith('管理员_'):
            continue
        
        if user.uid in guards:
            guard = guards[user.uid]
            if user.nickname != guard.nickname:
                discrepancies.append({
                    'table': 'User',
                    'uid': user.uid,
                    'current': user.nickname,
                    'correct': guard.nickname,
                    'record_id': user.id
                })
    
    return discrepancies


def apply_fixes(discrepancies):
    """应用修复"""
    fixed_count = 0
    
    for item in discrepancies:
        if item['table'] == 'Address':
            addr = Address.query.get(item['record_id'])
            if addr:
                addr.nickname = item['correct']
                fixed_count += 1
        elif item['table'] == 'User':
            user = User.query.get(item['record_id'])
            if user:
                user.nickname = item['correct']
                fixed_count += 1
    
    db.session.commit()
    return fixed_count


def main():
    parser = argparse.ArgumentParser(description='修复因缓存串号导致的昵称污染')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='只打印差异清单，不修改数据库（默认）')
    parser.add_argument('--apply', action='store_true',
                        help='应用修复，写库前自动备份 SQLite 到 backups/')
    
    args = parser.parse_args()
    
    # 如果指定了 --apply，则取消 --dry-run
    if args.apply:
        args.dry_run = False
    
    # 初始化 Flask 应用
    from app import create_app
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("昵称数据修复脚本")
        print("=" * 60)
        
        # 查找差异
        discrepancies = find_nickname_discrepancies()
        
        if not discrepancies:
            print("\n✓ 未发现昵称不一致的记录，无需修复。")
            return
        
        print(f"\n发现 {len(discrepancies)} 条昵称不一致的记录：\n")
        
        # 打印差异清单
        for i, item in enumerate(discrepancies, 1):
            print(f"{i}. [{item['table']}] UID: {item['uid']}")
            print(f"   当前值: {item['current']}")
            print(f"   正确值: {item['correct']}")
            print()
        
        if args.dry_run:
            print("=" * 60)
            print("DRY RUN 模式：未修改任何数据。")
            print("如需应用修复，请运行：python scripts/repair_nicknames.py --apply")
            print("=" * 60)
            return
        
        # 应用修复
        print("=" * 60)
        print("开始应用修复...")
        
        # 备份数据库
        db_path = get_db_path()
        if db_path and os.path.exists(db_path):
            backup_database(db_path)
        else:
            print(f"⚠ 未找到数据库文件: {db_path}")
            print("  跳过备份，继续修复...")
        
        # 执行修复
        fixed_count = apply_fixes(discrepancies)
        
        print(f"\n✓ 成功修复 {fixed_count} 条记录。")
        print("=" * 60)


if __name__ == '__main__':
    main()
