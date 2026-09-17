# coding:utf-8
"""
侧边栏图标。

全部用 QPainter 现画，不依赖 emoji 或图标字体 —— 那些在不同 Windows 版本上
渲染结果差别很大（有的变彩色 emoji、有的直接方块）。这里只画线和简单面。
每个函数签名统一是 paint(painter, rect, color)，rect 是正方形的绘制区。
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen


def _pen(p, color, w=1.7):
    pen = QPen(QColor(color))
    pen.setWidthF(w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pen


def _unit(rect):
    """把绘制区归一化成 0~1 的坐标，画笔宽度单独给，保证任何尺寸都清晰。"""
    s = min(rect.width(), rect.height())
    ox = rect.x() + (rect.width() - s) / 2.0
    oy = rect.y() + (rect.height() - s) / 2.0

    def pt(x, y):
        return QPointF(ox + x * s, oy + y * s)

    return pt, s


def paint_queue(p, rect, color):
    """下载：一个向下的箭头 + 托盘。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.105))
    p.drawLine(pt(0.5, 0.16), pt(0.5, 0.60))
    path = QPainterPath(pt(0.28, 0.40))
    path.lineTo(pt(0.5, 0.62))
    path.lineTo(pt(0.72, 0.40))
    p.drawPath(path)
    path2 = QPainterPath(pt(0.22, 0.72))
    path2.lineTo(pt(0.22, 0.84))
    path2.lineTo(pt(0.78, 0.84))
    path2.lineTo(pt(0.78, 0.72))
    p.drawPath(path2)


def paint_library(p, rect, color):
    """书库：三本立着的书。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.095))
    for x0 in (0.20, 0.42):
        p.drawLine(pt(x0, 0.20), pt(x0, 0.80))
    p.drawLine(pt(0.16, 0.20), pt(0.46, 0.20))
    p.drawLine(pt(0.16, 0.80), pt(0.46, 0.80))
    # 斜靠的第三本
    p.drawLine(pt(0.58, 0.80), pt(0.78, 0.24))
    p.drawLine(pt(0.72, 0.80), pt(0.88, 0.30))
    p.drawLine(pt(0.66, 0.22), pt(0.82, 0.28))


def paint_settings(p, rect, color):
    """设置：滑块。比齿轮简单，小尺寸下更清楚。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.095))
    for i, (y, x) in enumerate(((0.28, 0.62), (0.50, 0.36), (0.72, 0.58))):
        p.drawLine(pt(0.16, y), pt(0.84, y))
        p.setBrush(QColor(color))
        p.drawEllipse(pt(x, y), s * 0.105, s * 0.105)
        p.setBrush(Qt.BrushStyle.NoBrush)


def paint_help(p, rect, color):
    """帮助：圆里一个问号。问号用两段曲线近似，避免依赖字体。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.095))
    p.drawEllipse(pt(0.5, 0.5), s * 0.34, s * 0.34)
    path = QPainterPath(pt(0.37, 0.40))
    path.cubicTo(pt(0.37, 0.26), pt(0.63, 0.26), pt(0.63, 0.42))
    path.cubicTo(pt(0.63, 0.55), pt(0.50, 0.54), pt(0.50, 0.64))
    p.drawPath(path)
    p.setBrush(QColor(color))
    p.drawEllipse(pt(0.50, 0.755), s * 0.058, s * 0.058)
    p.setBrush(Qt.BrushStyle.NoBrush)


def paint_open_folder(p, rect, color):
    """打开所在文件夹。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.10))
    path = QPainterPath(pt(0.16, 0.76))
    path.lineTo(pt(0.16, 0.26))
    path.lineTo(pt(0.42, 0.26))
    path.lineTo(pt(0.50, 0.36))
    path.lineTo(pt(0.80, 0.36))
    p.drawPath(path)
    path2 = QPainterPath(pt(0.16, 0.76))
    path2.lineTo(pt(0.30, 0.46))
    path2.lineTo(pt(0.90, 0.46))
    path2.lineTo(pt(0.76, 0.76))
    path2.closeSubpath()
    p.drawPath(path2)


def paint_trash(p, rect, color):
    """移除。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.10))
    p.drawLine(pt(0.20, 0.28), pt(0.80, 0.28))
    p.drawLine(pt(0.40, 0.28), pt(0.40, 0.18))
    p.drawLine(pt(0.60, 0.28), pt(0.60, 0.18))
    p.drawLine(pt(0.40, 0.18), pt(0.60, 0.18))
    path = QPainterPath(pt(0.28, 0.34))
    path.lineTo(pt(0.33, 0.82))
    path.lineTo(pt(0.67, 0.82))
    path.lineTo(pt(0.72, 0.34))
    p.drawPath(path)


def paint_retry(p, rect, color):
    """重试：一个缺口圆 + 箭头。"""
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.10))
    p.drawArc(QRectF(pt(0.20, 0.20).x(), pt(0.20, 0.20).y(),
                     s * 0.60, s * 0.60), 60 * 16, 280 * 16)
    path = QPainterPath(pt(0.62, 0.18))
    path.lineTo(pt(0.82, 0.24))
    path.lineTo(pt(0.70, 0.42))
    p.drawPath(path)


def paint_plus(p, rect, color):
    pt, s = _unit(rect)
    _pen(p, color, max(1.4, s * 0.12))
    p.drawLine(pt(0.5, 0.22), pt(0.5, 0.78))
    p.drawLine(pt(0.22, 0.5), pt(0.78, 0.5))


def paint_check(p, rect, color):
    pt, s = _unit(rect)
    _pen(p, color, max(1.6, s * 0.14))
    path = QPainterPath(pt(0.22, 0.54))
    path.lineTo(pt(0.42, 0.72))
    path.lineTo(pt(0.78, 0.28))
    p.drawPath(path)


ICONS = {
    'queue': paint_queue,
    'library': paint_library,
    'settings': paint_settings,
    'help': paint_help,
    'folder': paint_open_folder,
    'trash': paint_trash,
    'retry': paint_retry,
    'plus': paint_plus,
    'check': paint_check,
}


def paint_icon(painter, name, rect, color):
    fn = ICONS.get(name)
    if fn is None:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fn(painter, rect, color)
    painter.restore()
