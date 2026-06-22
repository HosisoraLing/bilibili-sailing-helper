"""
舰长礼物服务模块
处理舰长礼物资格判断和每月统计
"""
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional

from db.models import db, Guard, GuardGiftRecord, get_beijing_now


class GuardGiftService:
    """舰长礼物服务类"""

    @staticmethod
    def is_eligible_for_gift(accompany_days: int, current_date: date, last_guard_date: Optional[date] = None) -> bool:
        """
        判断用户是否符合当月舰长礼物领取资格

        规则：
        1. 陪伴天数对30取余
        2. 余数若不为0，则用余数减去当前天数来判断
        3. 若结果 <= 0，则符合资格

        Args:
            accompany_days: 陪伴天数
            current_date: 当前日期

        Returns:
            bool: 是否符合资格
        """
        if accompany_days <= 0:
            return False

        # 陪伴天数对30取余
        remainder = accompany_days % 30

        # 余数为0，表示陪伴天数是30的倍数。
        # 新规则：当陪伴天数为30的整倍数时，只有同时满足：
        # 1) 用户仍在舰（last_guard_date 等于当前日期）
        # 2) 当前日期向前推30天仍在本月内（即 current_date - 30 天的月份 == current_date 的月份）
        # 才视为符合资格。
        if remainder == 0:
            if last_guard_date is None or last_guard_date != current_date:
                return False

            thirty_days_before = current_date - timedelta(days=30)
            # 如果向前30天仍在同一月份，则说明该 30 天周期完全落在本月内
            return thirty_days_before.month == current_date.month

        # 当前月份的天数
        current_month_days = current_date.day

        # 余数减去当前天数
        result = remainder - current_month_days

        # 结果 <= 0 表示符合资格
        return result <= 0

    @staticmethod
    def get_current_month() -> str:
        """获取当前月份，格式：YYYY-MM"""
        return date.today().strftime('%Y-%m')

    @staticmethod
    def get_last_day_of_month(year: int, month: int) -> date:
        """获取指定月份的最后一天"""
        if month == 12:
            return date(year + 1, 1, 1) - timedelta(days=1)
        return date(year, month + 1, 1) - timedelta(days=1)

    @staticmethod
    def calculate_monthly_eligible_guards(month: Optional[str] = None) -> List[GuardGiftRecord]:
        """
        计算指定月份的舰长礼物可用名单

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            List[GuardGiftRecord]: 符合资格的舰长礼物记录列表
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        # 获取所有在舰舰长
        guards = Guard.query.filter_by(in_guard=True).all()

        eligible_records = []

        for guard in guards:
            # 判断是否符合资格
            is_eligible = GuardGiftService.is_eligible_for_gift(
                guard.accompany_days or 0,
                date.today(),
                guard.last_guard_date
            )

            if is_eligible:
                # 检查是否已存在记录
                existing = GuardGiftRecord.query.filter_by(
                    uid=guard.uid,
                    month=month
                ).first()

                if not existing:
                    # 创建新的礼物记录
                    record = GuardGiftRecord(
                        uid=guard.uid,
                        nickname=guard.nickname,
                        month=month,
                        guard_level=guard.guard_level,
                        accompany_days=guard.accompany_days or 0,
                        received=False,
                        created_at=get_beijing_now(),
                        updated_at=get_beijing_now()
                    )
                    db.session.add(record)
                    eligible_records.append(record)
                else:
                    eligible_records.append(existing)

        # 收集本次符合资格的 UID 列表
        eligible_uids = {r.uid for r in eligible_records}

        # 查找该月份所有已存在的记录，删除不再符合资格且未领取的记录
        removed_any = False
        existing_month_records = GuardGiftRecord.query.filter_by(month=month).all()
        for rec in existing_month_records:
            if rec.uid not in eligible_uids and not rec.received:
                db.session.delete(rec)
                removed_any = True

        # 只有在新增或删除时才提交一次事务
        if eligible_records or removed_any:
            db.session.commit()

        # 返回当前（被保留或新增的）符合资格记录列表
        # 注意：eligible_records 包含新增的记录和原有被检测为符合资格的记录，
        # 对于之前存在但现在不符合的已领取记录仍保留在数据库中，但不会出现在 eligible_records 中。
        return eligible_records

    @staticmethod
    def get_monthly_eligible_records(month: Optional[str] = None) -> List[GuardGiftRecord]:
        """
        获取指定月份的舰长礼物可用名单

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            List[GuardGiftRecord]: 舰长礼物记录列表
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(month=month).all()

    @staticmethod
    def mark_gift_received(uid: str, month: Optional[str] = None) -> bool:
        """
        标记舰长礼物已领取

        Args:
            uid: 用户UID
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            bool: 是否成功标记
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        record = GuardGiftRecord.query.filter_by(
            uid=uid,
            month=month
        ).first()

        if record:
            record.received = True
            record.received_at = get_beijing_now()
            record.updated_at = get_beijing_now()
            db.session.commit()
            return True

        return False

    @staticmethod
    def get_eligible_count(month: Optional[str] = None) -> int:
        """
        获取指定月份符合资格的舰长数量

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            int: 符合资格的舰长数量
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(month=month).count()

    @staticmethod
    def get_received_count(month: Optional[str] = None) -> int:
        """
        获取指定月份已领取礼物的舰长数量

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            int: 已领取礼物的舰长数量
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(
            month=month,
            received=True
        ).count()

    @staticmethod
    def get_available_count(month: Optional[str] = None) -> int:
        """
        获取指定月份可领取礼物的舰长数量（符合资格但未领取）

        Args:
            month: 月份，格式：YYYY-MM，默认为当前月份

        Returns:
            int: 可领取礼物的舰长数量
        """
        if month is None:
            month = GuardGiftService.get_current_month()

        return GuardGiftRecord.query.filter_by(
            month=month,
            received=False
        ).count()

    @staticmethod
    def generate_eligible_csv(records: List[GuardGiftRecord]) -> str:
        """
        生成舰长礼物可用名单 CSV 内容

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
    def update_historical_months(months_back: int = 6) -> List[GuardGiftRecord]:
        """
        更新历史月份的舰长礼物记录
        
        根据当前陪伴天数反推历史月份是否符合资格，并创建/更新记录
        
        Args:
            months_back: 向前回溯的月数，默认6个月
            
        Returns:
            List[GuardGiftRecord]: 新增的记录列表
        """
        from sqlalchemy import distinct
        
        today = date.today()
        current_month = today.strftime('%Y-%m')
        
        # 获取所有在舰舰长
        guards = Guard.query.filter_by(in_guard=True).all()
        
        new_records = []
        
        # 获取已有记录的月份
        existing_months = set(
            m[0] for m in db.session.query(distinct(GuardGiftRecord.month)).all()
        )
        
        for guard in guards:
            if not guard.accompany_days or guard.accompany_days <= 0:
                continue
            
            # 回溯每个月份
            for i in range(1, months_back + 1):
                # 计算目标月份
                target_date = today.replace(day=1) - timedelta(days=i * 30)
                target_month = target_date.strftime('%Y-%m')
                
                # 跳过当前月份（由其他方法处理）
                if target_month == current_month:
                    continue
                
                # 获取该月最后一天
                year, month = map(int, target_month.split('-'))
                month_last_day = GuardGiftService.get_last_day_of_month(year, month)
                
                # 计算从该月最后一天到今天的天数差
                days_diff = (today - month_last_day).days
                
                # 计算当时的陪伴天数
                days_at_month = guard.accompany_days - days_diff
                
                if days_at_month <= 0:
                    continue
                
                # 判断当时是否符合资格
                # 使用简化规则：陪伴天数 % 30 的余数 <= 当月天数
                remainder = days_at_month % 30
                if remainder == 0:
                    # 30的倍数，需要特殊处理
                    # 简化：如果当时陪伴天数 >= 30 且在该月内达到30的倍数
                    is_eligible = (days_at_month >= 30) and (month_last_day.day >= 30)
                else:
                    is_eligible = remainder <= month_last_day.day
                
                if is_eligible:
                    # 检查是否已存在记录
                    existing = GuardGiftRecord.query.filter_by(
                        uid=guard.uid,
                        month=target_month
                    ).first()
                    
                    if not existing:
                        # 创建新记录
                        record = GuardGiftRecord(
                            uid=guard.uid,
                            nickname=guard.nickname,
                            month=target_month,
                            guard_level=guard.guard_level,
                            accompany_days=days_at_month,
                            received=False,
                            created_at=get_beijing_now(),
                            updated_at=get_beijing_now()
                        )
                        db.session.add(record)
                        new_records.append(record)
        
        if new_records:
            db.session.commit()
        
        return new_records

    @staticmethod
    def get_available_months() -> List[str]:
        """
        获取所有有记录的月份列表

        Returns:
            List[str]: 月份列表，格式：YYYY-MM
        """
        from sqlalchemy import distinct

        months = db.session.query(
            distinct(GuardGiftRecord.month)
        ).order_by(GuardGiftRecord.month.desc()).all()

        return [month[0] for month in months]
