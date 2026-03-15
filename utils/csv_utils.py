"""
CSV 工具函数
处理 CSV 文件的生成和响应
"""
from datetime import datetime
from flask import Response


def create_csv_response(csv_content: str, filename_prefix: str) -> Response:
    """
    创建 CSV 响应
    返回带有 UTF-8 BOM 的 CSV 文件，兼容 Excel
    """
    filename = f"{filename_prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        '\ufeff' + csv_content,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename={filename}'
        }
    )
