"""
管理员服务模块
处理管理员面板、地址管理、导出功能等业务逻辑
"""
from datetime import datetime, date
from typing import List, Tuple, Optional

from db.models import db, Address, Guard, GuardGiftRecord, get_beijing_now
from services.security import api_limiter, PasswordValidator
from services.guard_gift_service import GuardGiftService


class AdminService:
    """管理员服务类"""

    @staticmethod
    def check_admin_rate_limit(uid: str, action: str) -> Tuple[bool, Optional[int]]:
        """
        检查管理员操作速率限制
        返回: (is_allowed, wait_time)
        """
        return api_limiter.is_allowed(f"{action}_{uid}")

    @staticmethod
    def get_all_addresses() -> List[Address]:
        """获取所有已提交的地址"""
        return Address.query.order_by(Address.submitted_at.desc()).all()

    @staticmethod
    def get_address_by_id(address_id: int) -> Optional[Address]:
        """根据 ID 获取地址"""
        return Address.query.get(address_id)

    @staticmethod
    def delete_address(address_id: int) -> bool:
        """删除地址"""
        address = Address.query.get(address_id)
        if address:
            db.session.delete(address)
            db.session.commit()
            return True
        return False

    @staticmethod
    def validate_address_data(uid: str, phone: str) -> Tuple[bool, Optional[str]]:
        """
        验证地址数据
        返回: (is_valid, error_message)
        """
        # 验证 UID 格式
        is_valid, msg = PasswordValidator.validate_uid(uid)
        if not is_valid:
            return False, msg

        # 验证手机号格式
        is_valid, msg = PasswordValidator.validate_phone(phone)
        if not is_valid:
            return False, msg

        return True, None

    @staticmethod
    def check_guard_exists(uid: str) -> Tuple[bool, Optional[Guard]]:
        """
        检查舰长/陪伴榜用户是否存在
        返回: (exists, guard)
        """
        guard = Guard.query.filter_by(uid=uid).first()
        return guard is not None, guard

    @staticmethod
    def check_address_exists(uid: str) -> Tuple[bool, Optional[Address]]:
        """
        检查地址是否已存在
        返回: (exists, address)
        """
        address = Address.query.filter_by(uid=uid).first()
        return address is not None, address

    @staticmethod
    def create_address(uid: str, nickname: str, form_data: dict) -> Address:
        """创建新地址"""
        guard = Guard.query.filter_by(uid=uid).first()
        guard_level = guard.guard_level if guard else 'guard'

        address = Address(
            uid=uid,
            nickname=nickname,
            guard_level=guard_level,
            receiver=form_data.get('name', ''),
            phone=form_data.get('phone', ''),
            province=form_data.get('province', ''),
            city=form_data.get('city', ''),
            area=form_data.get('district', ''),
            address=form_data.get('detail', ''),
            submitted_at=get_beijing_now()
        )
        db.session.add(address)
        db.session.commit()
        return address

    @staticmethod
    def update_address(address: Address, form_data: dict) -> Address:
        """更新地址"""
        address.receiver = form_data.get('name', '')
        address.phone = form_data.get('phone', '')
        address.province = form_data.get('province', '')
        address.city = form_data.get('city', '')
        address.area = form_data.get('district', '')
        address.address = form_data.get('detail', '')
        db.session.commit()
        return address

    @staticmethod
    def get_all_guards() -> List[Guard]:
        """获取所有舰长"""
        return Guard.query.order_by(Guard.guard_level.desc(), Guard.updated_at.desc()).all()

    @staticmethod
    def count_guards_by_level(guards: List[Guard]) -> dict:
        """按等级统计舰长数量"""
        counts = {
            'guard': 0,      # 舰长
            'captain': 0,    # 提督
            'admiral': 0,    # 总督
        }
        for guard in guards:
            if guard.guard_level in counts:
                counts[guard.guard_level] += 1
        return counts

    @staticmethod
    def count_guards_by_status(guards: List[Guard]) -> dict:
        """按在舰状态统计舰长数量"""
        counts = {
            'in_guard': 0,      # 在舰
            'not_in_guard': 0,  # 不在舰
        }
        for guard in guards:
            if guard.in_guard:
                counts['in_guard'] += 1
            else:
                counts['not_in_guard'] += 1
        return counts

    @staticmethod
    def generate_addresses_csv(addresses: List[Address]) -> str:
        """生成地址 CSV 内容"""
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['UID', '昵称', '收件人', '手机号', '省', '市', '区', '详细地址', '提交时间'])

        # Data
        for addr in addresses:
            writer.writerow([
                addr.uid,
                addr.nickname,
                addr.receiver or '未填写',
                addr.phone or '未填写',
                addr.province or '未填写',
                addr.city or '未填写',
                addr.area or '未填写',
                addr.address or '未填写',
                addr.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if addr.submitted_at else '未提交'
            ])

        csv_content = output.getvalue()
        output.close()
        return csv_content

    @staticmethod
    def generate_guards_csv(guards: List[Guard]) -> str:
        """生成舰长 CSV 内容"""
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['UID', '昵称', '身份', '是否在舰', '陪伴天数', '最后在舰日期', '更新时间'])

        # Data
        for guard in guards:
            level_name = '舰长'
            if guard.guard_level == 'captain':
                level_name = '提督'
            elif guard.guard_level == 'admiral':
                level_name = '总督'

            in_guard_status = '是' if guard.in_guard else '否'

            writer.writerow([
                guard.uid,
                guard.nickname,
                level_name,
                in_guard_status,
                guard.accompany_days or 0,
                guard.last_guard_date.strftime('%Y-%m-%d') if guard.last_guard_date else '',
                guard.updated_at.strftime('%Y-%m-%d %H:%M:%S') if guard.updated_at else ''
            ])

        csv_content = output.getvalue()
        output.close()
        return csv_content

    @staticmethod
    def get_csv_filename(prefix: str) -> str:
        """生成 CSV 文件名"""
        return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    # =========================
    # 舰长礼物相关功能
    # =========================

    @staticmethod
    def get_all_guard_gift_records(month: Optional[str] = None) -> List[GuardGiftRecord]:
        """
        获取舰长礼物记录

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份。如果为None，返回所有月份。

        Returns:
            List[GuardGiftRecord]: 舰长礼物记录列表
        """
        query = GuardGiftRecord.query
        
        if month is not None:
            query = query.filter_by(month=month)
        
        return query.order_by(
            GuardGiftRecord.month.desc(),
            GuardGiftRecord.guard_level.desc(),
            GuardGiftRecord.created_at.desc()
        ).all()

    @staticmethod
    def get_eligible_guard_gift_records(month: Optional[str] = None) -> List[GuardGiftRecord]:
        """
        获取符合资格的舰长礼物记录（未领取）

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            List[GuardGiftRecord]: 符合资格的舰长礼物记录列表
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(
            month=month,
            received=False
        ).order_by(
            GuardGiftRecord.guard_level.desc(),
            GuardGiftRecord.created_at.desc()
        ).all()

    @staticmethod
    def get_received_guard_gift_records(month: Optional[str] = None) -> List[GuardGiftRecord]:
        """
        获取已领取礼物的舰长礼物记录

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            List[GuardGiftRecord]: 已领取礼物的舰长礼物记录列表
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(
            month=month,
            received=True
        ).order_by(
            GuardGiftRecord.guard_level.desc(),
            GuardGiftRecord.received_at.desc()
        ).all()

    @staticmethod
    def count_guard_gift_records(month: Optional[str] = None) -> dict:
        """
        统计舰长礼物记录数量

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            dict: 统计结果
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        total = GuardGiftRecord.query.filter_by(month=month).count()
        eligible = GuardGiftRecord.query.filter_by(month=month, received=False).count()
        received = GuardGiftRecord.query.filter_by(month=month, received=True).count()

        return {
            'total': total,
            'eligible': eligible,
            'received': received
        }

    @staticmethod
    def generate_guard_gift_csv(records: List[GuardGiftRecord]) -> str:
        """
        生成舰长礼物记录 CSV 内容

        Args:
            records: 舰长礼物记录列表

        Returns:
            str: CSV 内容
        """
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['月份', 'UID', '昵称', '身份', '陪伴天数', '是否已领取', '领取时间', '创建时间'])

        # Data
        for record in records:
            level_name = '舰长'
            if record.guard_level == 'captain':
                level_name = '提督'
            elif record.guard_level == 'admiral':
                level_name = '总督'

            received_status = '是' if record.received else '否'
            received_time = record.received_at.strftime('%Y-%m-%d %H:%M:%S') if record.received_at else '-'

            writer.writerow([
                record.month,
                record.uid,
                record.nickname,
                level_name,
                record.accompany_days or 0,
                received_status,
                received_time,
                record.created_at.strftime('%Y-%m-%d %H:%M:%S') if record.created_at else '-'
            ])

        csv_content = output.getvalue()
        output.close()
        return csv_content

    @staticmethod
    def get_available_months() -> List[str]:
        """
        获取所有有记录的月份列表

        Returns:
            List[str]: 月份列表，格式：YYYY-MM
        """
        return GuardGiftService.get_available_months()

    @staticmethod
    def mark_guard_gift_received(uid: str, month: Optional[str] = None) -> bool:
        """
        标记舰长礼物已领取

        Args:
            uid: 用户UID
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            bool: 是否成功标记
        """
        return GuardGiftService.mark_gift_received(uid, month)
