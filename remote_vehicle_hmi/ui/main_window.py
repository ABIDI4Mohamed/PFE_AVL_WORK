"""
Vehicle Command HMI  ·  main_window.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cinematic automotive redesign.
All UDP, timers and signal connections preserved exactly.

Fixes vs previous version
──────────────────────────
• Steering drag: right → positive angle (corrected sign)
• Viewer: fills frame edge-to-edge, no offset artefacts
• Alert overlay: animated pulsing red border + dim overlay on
  emergency-active or fault=YES
• Brake pedal: distinct amber-orange colour (not red)
• Full cinematic dark-automotive aesthetic
"""

import csv
import math
import time
import win32gui
import win32con
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QPen, QColor, QFont, QLinearGradient,
    QBrush, QRadialGradient, QPainterPath, QFontDatabase,
)
from PySide6.QtWidgets import (
    QDial, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QVBoxLayout,
    QWidget, QSizePolicy, QStackedWidget,
)

from comm.udp_link import UDPLink
from scenarios.scenario_reference import ScenarioReference


# ═══════════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════
C = {
    # backgrounds  (3 depth levels)
    "bg0":       "#03080f",   # void — outer chrome
    "bg1":       "#070e1a",   # panel surface
    "bg2":       "#0a1422",   # card fill
    "bg3":       "#0e1c2e",   # inner element
    "bg4":       "#121f30",   # hovered / selected

    # borders
    "bdr":       "#162540",
    "bdr2":      "#1e3456",
    "bdr3":      "#28446e",   # accent border

    # typography
    "txt0":      "#ecf4ff",   # primary
    "txt1":      "#6a94c4",   # secondary
    "txt2":      "#2e4d6e",   # muted / hint

    # semantic accents
    "cyan":      "#00c8e8",   # primary accent
    "cyan_dim":  "#003a48",
    "green":     "#00dfa0",   # accel / ok
    "green_dim": "#00200e",
    "orange":    "#ff8c00",   # brake (distinct, warm)
    "orange_dim":"#2a1800",
    "amber":     "#f5a623",   # reset / warning
    "amber_dim": "#1f1200",
    "red":       "#e8302a",   # emergency / fault
    "red_dim":   "#2a0808",
    "red_hot":   "#ff5555",   # pulsing alert
}


# ═══════════════════════════════════════════════════════════════
#  ALERT OVERLAY  — flashes over the viewer on EMERGENCY / FAULT
# ═══════════════════════════════════════════════════════════════
class AlertOverlay(QWidget):
    """
    Transparent widget stacked on top of the viewer.
    When active: draws a pulsing red vignette border + warning text.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setVisible(False)

        self._alpha   = 0.0       # 0.0 … 1.0  (pulsed by timer)
        self._message = "EMERGENCY STOP"
        self._dir     = 1
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start(30)

    def set_alert(self, active: bool, message: str = "EMERGENCY STOP"):
        self._message = message
        self.setVisible(active)
        if not active:
            self._alpha = 0.0

    def _pulse(self):
        self._alpha += self._dir * 0.04
        if self._alpha >= 1.0:
            self._alpha = 1.0
            self._dir   = -1
        elif self._alpha <= 0.0:
            self._alpha = 0.0
            self._dir   =  1
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        a    = self._alpha

        # pulsing red vignette border
        border_w = int(18 + a * 14)
        for i in range(border_w, 0, -1):
            frac   = i / border_w
            alpha  = int(frac * a * 200)
            p.setPen(QPen(QColor(232, 48, 42, alpha), 2))
            p.drawRoundedRect(QRectF(i, i, w-2*i, h-2*i), 10, 10)

        # semi-transparent dim
        dim_alpha = int(a * 38)
        p.fillRect(self.rect(), QColor(30, 0, 0, dim_alpha))

        # warning banner at top
        banner_h = 44
        bg_a = int(a * 200)
        p.fillRect(QRectF(0, 0, w, banner_h), QColor(180, 20, 20, bg_a))

        p.setPen(QColor(255, 220, 220, int(a * 255)))
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.drawText(QRectF(0, 0, w, banner_h),
                   Qt.AlignCenter, f"⚠  {self._message}  ⚠")
        p.end()


# ═══════════════════════════════════════════════════════════════
#  ASPECT-RATIO VIEWER FRAME  (logic unchanged)
# ═══════════════════════════════════════════════════════════════
class AspectRatioFrame(QFrame):
    def __init__(self, aspect_w=16, aspect_h=9, parent=None):
        super().__init__(parent)
        self.setObjectName("videoFrame")
        self.aspect_w      = aspect_w
        self.aspect_h      = aspect_h
        self.embedded_hwnd = None

        # alert overlay sits on top
        self.alert_overlay = AlertOverlay(self)

    def set_alert(self, active: bool, message: str = "EMERGENCY STOP"):
        self.alert_overlay.set_alert(active, message)

    def set_embedded_hwnd(self, hwnd: int):
        self.embedded_hwnd = hwnd
        self._resize_embedded()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.alert_overlay.setGeometry(self.rect())
        self._resize_embedded()

    def _resize_embedded(self):
        if not self.embedded_hwnd or not win32gui.IsWindow(self.embedded_hwnd):
            return

        host_w = max(1, self.width())
        host_h = max(1, self.height())

        target_ratio = self.aspect_w / self.aspect_h
        host_ratio = host_w / host_h

        # Fit a centered 16:9 client area inside the host
        if host_ratio > target_ratio:
            draw_h = host_h
            draw_w = int(draw_h * target_ratio)
            draw_x = (host_w - draw_w) // 2
            draw_y = 0
        else:
            draw_w = host_w
            draw_h = int(draw_w / target_ratio)
            draw_x = 0
            draw_y = (host_h - draw_h) // 2

        try:
            # Measure full embedded window vs client area to compensate
            # non-client remnants and align the client area to the centered box.
            wr = win32gui.GetWindowRect(self.embedded_hwnd)
            cr = win32gui.GetClientRect(self.embedded_hwnd)

            win_w = max(1, wr[2] - wr[0])
            win_h = max(1, wr[3] - wr[1])
            cli_w = max(1, cr[2] - cr[0])
            cli_h = max(1, cr[3] - cr[1])

            border_x = max(0, (win_w - cli_w) // 2)
            border_y_total = max(0, win_h - cli_h)
            top_bar = max(0, border_y_total - border_x)
            bottom_bar = max(0, border_x)

            x = draw_x - border_x
            y = draw_y - top_bar
            w = draw_w + 2 * border_x
            h = draw_h + top_bar + bottom_bar

            win32gui.MoveWindow(self.embedded_hwnd, x, y, w, h, True)

        except Exception:
            # Fallback: still center the window cleanly
            try:
                win32gui.MoveWindow(
                    self.embedded_hwnd,
                    draw_x,
                    draw_y,
                    draw_w,
                    draw_h,
                    True,
                )
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#  PEDAL BAR  (custom vertical slider)
# ═══════════════════════════════════════════════════════════════
class PedalBar(QWidget):
    def __init__(self, fill_hex: str, parent=None):
        super().__init__(parent)
        self._value     = 0
        self._min       = 0
        self._max       = 100
        self._fill      = QColor(fill_hex)
        self._dragging  = False
        self._on_change = None
        self.setFixedWidth(52)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

    # ── interface ──────────────────────────────────────────────
    def value(self) -> int: return self._value

    def setValue(self, v: int):
        v = max(self._min, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.update()

    def setRange(self, mn: int, mx: int):
        self._min, self._max = mn, mx

    # ── geometry ───────────────────────────────────────────────
    def _bar(self) -> QRectF:
        m = 10
        return QRectF(m, m, self.width() - 2*m, self.height() - 2*m)

    def _ratio(self) -> float:
        return (self._value - self._min) / max(1, self._max - self._min)

    def _val_to_y(self, v: int) -> float:
        r = self._bar()
        return r.bottom() - (v - self._min) / max(1, self._max - self._min) * r.height()

    def _y_to_val(self, y: float) -> int:
        r = self._bar()
        ratio = (r.bottom() - y) / r.height()
        return int(max(self._min, min(self._max, ratio * (self._max - self._min) + self._min)))

    # ── paint ──────────────────────────────────────────────────
    def paintEvent(self, event):
        p   = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r   = self._bar()
        rx  = 7.0

        # ── track ──
        p.setBrush(QBrush(QColor(C["bg3"])))
        p.setPen(QPen(QColor(C["bdr"]), 1))
        p.drawRoundedRect(r, rx, rx)

        # ── subtle segment lines ──
        seg = 10
        p.setPen(QPen(QColor(C["bdr"]), 0.6))
        for i in range(1, seg):
            y = r.top() + i/seg * r.height()
            p.drawLine(QPointF(r.left()+2, y), QPointF(r.right()-2, y))

        # ── fill (bottom → up) ──
        ratio = self._ratio()
        if ratio > 0.001:
            fh = r.height() * ratio
            fr = QRectF(r.left(), r.bottom() - fh, r.width(), fh)
            g  = QLinearGradient(QPointF(r.left(), r.bottom() - fh),
                                 QPointF(r.left(), r.bottom()))
            g.setColorAt(0.0, self._fill.lighter(130))
            g.setColorAt(0.5, self._fill)
            g.setColorAt(1.0, self._fill.darker(160))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            clip = QPainterPath()
            clip.addRoundedRect(r, rx, rx)
            p.setClipPath(clip)
            p.drawRect(fr)
            p.setClipping(False)

            # top glow line
            top_col = self._fill.lighter(180)
            top_col.setAlpha(200)
            p.setPen(QPen(top_col, 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(r.left()+rx, r.bottom()-fh),
                       QPointF(r.right()-rx, r.bottom()-fh))

        # ── handle (horizontal pill) ──
        hy    = self._val_to_y(self._value)
        hc    = self._fill.lighter(160)
        hw    = r.width() - 4
        hrect = QRectF(r.left() + 2, hy - 4, hw, 8)
        p.setBrush(QBrush(hc))
        p.setPen(QPen(QColor(255,255,255,60), 1))
        p.drawRoundedRect(hrect, 4, 4)

        p.end()

    # ── interaction ────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._set_from_y(e.position().y())

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._set_from_y(e.position().y())

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def wheelEvent(self, e):
        self._set_val(self._value + (1 if e.angleDelta().y() > 0 else -1))

    def _set_from_y(self, y):
        self._set_val(self._y_to_val(y))

    def _set_val(self, v):
        v = max(self._min, min(self._max, v))
        if v != self._value:
            self._value = v
            self.update()
            if self._on_change:
                self._on_change(v)


# ═══════════════════════════════════════════════════════════════
#  STEERING WHEEL  (custom painted)
# ═══════════════════════════════════════════════════════════════
class SteeringWheel(QWidget):
    """
    Drag right → positive angle.
    Drag left  → negative angle.
    (atan2 gives the mathematical angle; dragging right increases x,
     which increases angle, which we map directly to steer_cmd.)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value            = 0
        self._min              = -90
        self._max              =  90
        self._span             = 140        # arc half-span in degrees
        self._dragging         = False
        self._drag_start_angle = 0.0
        self._drag_start_value = 0
        self._on_change        = None
        self.setFixedSize(190, 190)
        self.setCursor(Qt.PointingHandCursor)

    def value(self) -> int: return self._value

    def setValue(self, v: int):
        v = max(self._min, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.update()

    # ── paint ──────────────────────────────────────────────────
    def paintEvent(self, event):
        p       = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h    = self.width(), self.height()
        cx, cy  = w/2, h/2
        R       = min(w, h)/2 - 5

        # outer bezel ring
        bezel_g = QRadialGradient(cx, cy - R*0.3, R*1.3)
        bezel_g.setColorAt(0.70, QColor(C["bg3"]))
        bezel_g.setColorAt(0.85, QColor(C["bdr3"]))
        bezel_g.setColorAt(1.00, QColor(C["bg2"]))
        p.setBrush(QBrush(bezel_g))
        p.setPen(QPen(QColor(C["bdr3"]), 1.5))
        p.drawEllipse(QPointF(cx, cy), R, R)

        # arc track
        arc_r    = R - 9
        arc_rect = QRectF(cx-arc_r, cy-arc_r, 2*arc_r, 2*arc_r)
        p.setPen(QPen(QColor(C["bdr"]), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, int((90-self._span)*16), int(2*self._span*16))

        # coloured progress arc
        ratio = self._value / 90.0
        if abs(ratio) > 0.01:
            arc_col = QColor(C["cyan"])
            p.setPen(QPen(arc_col, 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(arc_rect, 90*16, int(-ratio * self._span * 16))

        # tick marks
        for i in range(-8, 9):
            frac  = i / 8.0
            a_deg = 90 - frac * self._span
            a     = math.radians(a_deg)
            major = (i % 4 == 0)
            o_r   = arc_r - 1
            i_r   = arc_r - (12 if major else 6)
            p.setPen(QPen(QColor(C["bdr3"] if major else C["bdr"]),
                          1.5 if major else 1))
            p.drawLine(QPointF(cx+i_r*math.cos(a), cy-i_r*math.sin(a)),
                       QPointF(cx+o_r*math.cos(a), cy-o_r*math.sin(a)))

        # centre knob face
        knob_r = R - 18
        kg = QRadialGradient(cx - knob_r*0.12, cy - knob_r*0.18, knob_r*1.15)
        kg.setColorAt(0.0, QColor("#182a3e"))
        kg.setColorAt(0.6, QColor("#0e1e30"))
        kg.setColorAt(1.0, QColor("#060c1a"))
        p.setBrush(QBrush(kg))
        p.setPen(QPen(QColor(C["bdr"]), 1))
        p.drawEllipse(QPointF(cx, cy), knob_r, knob_r)

        # HMI brand cross-hairs (very subtle)
        p.setPen(QPen(QColor(C["bdr"]), 0.8))
        p.drawLine(QPointF(cx - knob_r*0.5, cy), QPointF(cx + knob_r*0.5, cy))
        p.drawLine(QPointF(cx, cy - knob_r*0.5), QPointF(cx, cy + knob_r*0.5))

        # indicator dot (rotates with steering angle)
        dot_r = knob_r - 14
        a_deg = 90 - ratio * self._span
        a     = math.radians(a_deg)
        dx    = cx + dot_r * math.cos(a)
        dy    = cy - dot_r * math.sin(a)

        # glow halo
        glow = QRadialGradient(dx, dy, 16)
        glow.setColorAt(0.0, QColor(0, 200, 232, 120))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(dx, dy), 16, 16)

        # dot
        p.setBrush(QBrush(QColor(C["cyan"])))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.drawEllipse(QPointF(dx, dy), 6, 6)

        # centre hub
        hub_g = QRadialGradient(cx, cy, 10)
        hub_g.setColorAt(0, QColor(C["cyan"]))
        hub_g.setColorAt(1, QColor(C["cyan_dim"]))
        p.setBrush(QBrush(hub_g))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 6, 6)

        p.end()

    # ── interaction — drag right = steer right = positive ──────
    def _angle(self, x, y) -> float:
        # Standard mathematical angle: right=0°, up=90°, left=180°
        return math.degrees(math.atan2(-(y - self.height()/2),
                                        x - self.width()/2))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging         = True
            self._drag_start_angle = self._angle(e.position().x(), e.position().y())
            self._drag_start_value = self._value

    def mouseMoveEvent(self, e):
        if not self._dragging:
            return
        cur   = self._angle(e.position().x(), e.position().y())
        delta = cur - self._drag_start_angle
        # Wrap delta into −180 … +180
        if delta >  180: delta -= 360
        if delta < -180: delta += 360
        # CORRECT DIRECTION: moving the cursor clockwise (right side down)
        # reduces the mathematical angle → negative delta → negate for steer
        # Dragging right along the bottom arc: angle decreases → negate
        # so that right-drag → positive steer.
        nv = max(self._min, min(self._max, int(self._drag_start_value - delta)))
        if nv != self._value:
            self._value = nv
            self.update()
            if self._on_change:
                self._on_change(nv)

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def wheelEvent(self, e):
        d  = 1 if e.angleDelta().y() > 0 else -1
        nv = max(self._min, min(self._max, self._value + d))
        if nv != self._value:
            self._value = nv
            self.update()
            if self._on_change:
                self._on_change(nv)


# ═══════════════════════════════════════════════════════════════
#  SPEEDOMETER
# ═══════════════════════════════════════════════════════════════
class SpeedometerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.speed_kmh     = 0.0
        self.speed_mps     = 0.0
        self.max_speed_kmh = 220.0
        self.setMinimumSize(180, 210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_speed(self, speed_mps: float):
        self.speed_mps = max(0.0, speed_mps)
        self.speed_kmh = self.speed_mps * 3.6
        self.update()

    def paintEvent(self, event):
        p     = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h  = self.width(), self.height()
        cx    = w / 2
        cy    = h / 2 + 18
        R     = min(w * 0.42, (h - 72) * 0.50)

        start = 225
        span  = 270
        ratio = min(max(self.speed_kmh / self.max_speed_kmh, 0.0), 1.0)

        arc_rect = QRectF(cx-R, cy-R, 2*R, 2*R)

        # glow backing ring
        p.setPen(QPen(QColor(0, 200, 232, 18), 18, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, start*16, -span*16)

        # dark track
        p.setPen(QPen(QColor(C["bg3"]), 10, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, start*16, -span*16)

        # progress arc — colour shifts with speed
        col = (QColor(C["green"])  if ratio < 0.50 else
               QColor(C["amber"])  if ratio < 0.75 else
               QColor(C["red"]))
        p.setPen(QPen(col, 7, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, start*16, int(-span*ratio*16))

        # ticks
        for i in range(29):
            frac  = i / 28
            a     = math.radians(start - span*frac)
            major = (i % 4 == 0)
            o_r   = R + 4
            i_r   = R - (14 if major else 7)
            p.setPen(QPen(QColor(C["txt1"] if major else C["bdr3"]),
                          1.5 if major else 1))
            p.drawLine(QPointF(cx+i_r*math.cos(a), cy-i_r*math.sin(a)),
                       QPointF(cx+o_r*math.cos(a), cy-o_r*math.sin(a)))

        # labels
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        for v in [0, 40, 80, 120, 160, 200]:
            a  = math.radians(start - span * v/self.max_speed_kmh)
            tr = R - 24
            tx, ty = cx + tr*math.cos(a), cy - tr*math.sin(a)
            p.setPen(QColor(C["txt1"]))
            p.drawText(QRectF(tx-14, ty-8, 28, 16), Qt.AlignCenter, str(v))

        # needle
        na = math.radians(start - span*ratio)
        nl = R - 16
        nx, ny = cx + nl*math.cos(na), cy - nl*math.sin(na)
        p.setPen(QPen(QColor(0,0,0,80), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx+1, cy+1), QPointF(nx+1, ny+1))
        p.setPen(QPen(QColor("#ffffff"), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(nx, ny))

        # hub
        hg = QRadialGradient(cx, cy, 10)
        hg.setColorAt(0, QColor(C["bdr3"]))
        hg.setColorAt(1, QColor(C["bg0"]))
        p.setBrush(QBrush(hg))
        p.setPen(QPen(QColor(C["bdr"]), 1))
        p.drawEllipse(QPointF(cx, cy), 9, 9)

        # speed readout
        p.setPen(QColor(C["txt0"]))
        p.setFont(QFont("Segoe UI", 26, QFont.Bold))
        p.drawText(QRectF(0, 0, w, 40), Qt.AlignCenter, f"{self.speed_kmh:.1f}")

        p.setPen(QColor(C["cyan"]))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(0, 36, w, 18), Qt.AlignCenter, "km/h")

        p.setPen(QColor(C["txt2"]))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(0, 52, w, 16), Qt.AlignCenter, f"{self.speed_mps:.1f} m/s")

        p.end()


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def _hsep() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C['bdr']}; border:none; margin:0px 4px;")
    return f

def _vsep() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setFixedHeight(28)
    f.setStyleSheet(f"background:{C['bdr']}; border:none;")
    return f



# ═══════════════════════════════════════════════════════════════
#  SESSION LOGGER
# ═══════════════════════════════════════════════════════════════
class SessionLogger:
    """
    CSV logger for manual driving sessions.
    Writes one row per HMI feedback cycle.
    """

    HEADER = [
        "timestamp_s",
        "session_id",
        "scenario_id",
        "phase",
        "steer_in_deg",
        "throttle_in",
        "brake_in",
        "speed_mps",
        "yaw_rad",
        "yaw_rate_rps",
        "mode_id",
        "fault_flag",
        "rtt_s",
        "jitter_s",
        "steer_ref_deg",
        "throttle_ref",
        "brake_ref",
        "speed_ref_mps",
        "tol_steer_deg",
        "tol_throttle",
        "tol_brake",
        "tol_speed_mps",
        "e_steer_deg",
        "e_throttle",
        "e_brake",
        "e_speed_mps",
    ]

    def __init__(self, csv_path: Path, session_id: str, scenario_id: str) -> None:
        self.csv_path = Path(csv_path)
        self.session_id = session_id
        self.scenario_id = scenario_id
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.csv_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.HEADER)
        self._writer.writeheader()
        self._fh.flush()

    def write_row(self, row: dict) -> None:
        safe_row = {k: row.get(k, "") for k in self.HEADER}
        self._writer.writerow(safe_row)
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vehicle Command HMI")
        self.resize(1600, 920)

        # ── command state ──────────────────────────────────────
        self.steer_cmd_deg     = 0
        self.accel_cmd_percent = 0
        self.brake_cmd_percent = 0
        self.emergency_active  = 0.0
        self.reset_cmd         = 0.0

        self.last_manual_input_time = 0.0
        self.manual_guard_time      = 0.05
        self.heartbeat_period_ms    = 20

        # ── UDP ────────────────────────────────────────────────
        self.udp_link = UDPLink(send_port=25000, recv_port=25001)
        self.udp_link.start_receiver()

        # ── Scenario reference integration ─────────────────────
        self.scenario_ref: Optional[ScenarioReference] = None
        self.active_scenario_id: str = "SC01"
        self.session_t0: float = time.perf_counter()
        self.current_reference: Optional[Dict[str, Any]] = None
        self.current_phase: str = "N/A"
        self.scenario_loaded: bool = False

        self._init_scenario_reference()

        # ── Session logging ────────────────────────────────────
        self.session_id: str = time.strftime("S%Y%m%d_%H%M%S")
        self.logs_dir: Path = Path("logs")
        self.session_logger: Optional[SessionLogger] = None
        self.logging_enabled: bool = True

        # ── Command mode ───────────────────────────────────────
        self.use_auto_scenario: bool = True

        self._init_session_logger()

        # ── viewer embedding ───────────────────────────────────
        self.viewer_hwnd     = None
        self.viewer_embedded = False

        # ── timers ─────────────────────────────────────────────
        self.reset_pulse_timer = QTimer(self)
        self.reset_pulse_timer.setSingleShot(True)
        self.reset_pulse_timer.timeout.connect(self._clear_reset_cmd)

        self._setup_ui()
        self._apply_styles()
        self._connect_signals()

        self.command_timer = QTimer(self)
        self.command_timer.timeout.connect(self._send_heartbeat_command)
        self.command_timer.start(self.heartbeat_period_ms)

        self.feedback_timer = QTimer(self)
        self.feedback_timer.timeout.connect(self._update_feedback_display)
        self.feedback_timer.start(50)

        self.viewer_timer = QTimer(self)
        self.viewer_timer.timeout.connect(self._ensure_viewer_embedded)
        self.viewer_timer.start(1000)

    # ══════════════════════════════════════════════════════════
    #  SCENARIO REFERENCE
    # ══════════════════════════════════════════════════════════
    def _init_scenario_reference(self) -> None:
        try:
            scenario_csv = Path("scenarios/scenario_reference_SC01_slow_manual_friendly.csv")
            if scenario_csv.exists():
                self.scenario_ref = ScenarioReference(scenario_csv)
                self.scenario_loaded = True
                print(f"[SCENARIO] Loaded: {scenario_csv}")
                print(f"[SCENARIO] Available scenarios: {self.scenario_ref.list_scenarios()}")
            else:
                print(f"[SCENARIO] CSV not found: {scenario_csv}")
        except Exception as exc:
            self.scenario_ref = None
            self.scenario_loaded = False
            print(f"[SCENARIO] Load failed: {exc}")

    def _get_current_reference(self) -> Optional[Dict[str, Any]]:
        if not self.scenario_loaded or self.scenario_ref is None:
            self.current_reference = None
            self.current_phase = "N/A"
            return None

        t_s = time.perf_counter() - self.session_t0
        try:
            ref = self.scenario_ref.get_reference_at_time(self.active_scenario_id, t_s)
            self.current_reference = ref
            if ref is not None:
                self.current_phase = str(ref.get("phase", "N/A"))
            else:
                self.current_phase = "N/A"
            return ref
        except Exception as exc:
            print(f"[SCENARIO] Reference retrieval failed: {exc}")
            self.current_reference = None
            self.current_phase = "N/A"
            return None

    def get_tracking_errors(self) -> Optional[Dict[str, float]]:
        ref = self._get_current_reference()
        if ref is None:
            return None

        fb = self.udp_link.latest_feedback
        speed_mps = float(fb.get("speed_mps", 0.0))
        cmd = self._get_active_command_values()

        return {
            "e_steer_deg": float(cmd["steer_deg"]) - float(ref["steer_ref_deg"]),
            "e_throttle": float(cmd["throttle"]) - float(ref["throttle_ref"]),
            "e_brake": float(cmd["brake"]) - float(ref["brake_ref"]),
            "e_speed_mps": speed_mps - float(ref["speed_ref_mps"]),
        }

    def _get_active_command_values(self) -> Dict[str, float]:
        if self.use_auto_scenario and self.scenario_loaded:
            ref = self.current_reference or self._get_current_reference()
            if ref is not None:
                return {
                    "steer_deg": float(ref["steer_ref_deg"]),
                    "throttle": float(ref["throttle_ref"]),
                    "brake": float(ref["brake_ref"]),
                }

        return {
            "steer_deg": float(self.steer_cmd_deg),
            "throttle": self.accel_cmd_percent / 100.0,
            "brake": self.brake_cmd_percent / 100.0,
        }

    def _update_auto_command_display(self) -> None:
        if not self.use_auto_scenario or not self.scenario_loaded:
            return

        ref = self.current_reference or self._get_current_reference()
        if ref is None:
            return

        steer_deg = float(ref["steer_ref_deg"])
        throttle = float(ref["throttle_ref"])
        brake = float(ref["brake_ref"])

        sign = "+" if steer_deg > 0 else ""
        self.steer_value_label.setText(f"{sign}{steer_deg:.0f}°")
        self.accel_value_label.setText(f"{throttle * 100:.0f}%")
        self.brake_value_label.setText(f"{brake * 100:.0f}%")

        try:
            self.steer_dial.setValue(int(round(steer_deg)))
            self.accel_slider.setValue(int(round(throttle * 100)))
            self.brake_slider.setValue(int(round(brake * 100)))
        except Exception:
            pass

    def _init_session_logger(self) -> None:
        if not self.logging_enabled:
            return

        try:
            scenario_name = self.active_scenario_id if self.scenario_loaded else "NO_SCENARIO"
            log_filename = f"{self.session_id}_{scenario_name}.csv"
            log_path = self.logs_dir / log_filename
            self.session_logger = SessionLogger(
                csv_path=log_path,
                session_id=self.session_id,
                scenario_id=scenario_name,
            )
            print(f"[LOGGER] Logging session to: {log_path}")
        except Exception as exc:
            self.session_logger = None
            print(f"[LOGGER] Failed to initialize logger: {exc}")

    def _log_current_sample(self) -> None:
        if not self.logging_enabled or self.session_logger is None:
            return

        try:
            fb = self.udp_link.latest_feedback or {}
            ref = self.current_reference or self._get_current_reference()
            errs = self.get_tracking_errors()

            cmd = self._get_active_command_values()

            row = {
                "timestamp_s": round(time.perf_counter() - self.session_t0, 3),
                "session_id": self.session_id,
                "scenario_id": self.active_scenario_id if self.scenario_loaded else "N/A",
                "phase": self.current_phase,
                "steer_in_deg": float(cmd["steer_deg"]),
                "throttle_in": float(cmd["throttle"]),
                "brake_in": float(cmd["brake"]),
                "speed_mps": float(fb.get("speed_mps", 0.0)),
                "yaw_rad": float(fb.get("yaw_rad", 0.0)),
                "yaw_rate_rps": float(fb.get("yaw_rate_rps", 0.0)),
                "mode_id": int(round(float(fb.get("mode_id", 0.0)))),
                "fault_flag": int(round(float(fb.get("fault_flag", 0.0)))),
                "rtt_s": float(fb.get("rtt_s", 0.0)),
                "jitter_s": float(fb.get("jitter_s", 0.0)),
                "steer_ref_deg": float(ref["steer_ref_deg"]) if ref else "",
                "throttle_ref": float(ref["throttle_ref"]) if ref else "",
                "brake_ref": float(ref["brake_ref"]) if ref else "",
                "speed_ref_mps": float(ref["speed_ref_mps"]) if ref else "",
                "tol_steer_deg": float(ref["tol_steer_deg"]) if ref else "",
                "tol_throttle": float(ref["tol_throttle"]) if ref else "",
                "tol_brake": float(ref["tol_brake"]) if ref else "",
                "tol_speed_mps": float(ref["tol_speed_mps"]) if ref else "",
                "e_steer_deg": float(errs["e_steer_deg"]) if errs else "",
                "e_throttle": float(errs["e_throttle"]) if errs else "",
                "e_brake": float(errs["e_brake"]) if errs else "",
                "e_speed_mps": float(errs["e_speed_mps"]) if errs else "",
            }

            self.session_logger.write_row(row)
        except Exception as exc:
            print(f"[LOGGER] Failed to write sample: {exc}")

    # ══════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════
    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_left(),   20)
        root.addWidget(self._build_center(), 58)
        root.addWidget(self._build_right(),  22)

    # ─────────────────────────────────────────────────────────
    #  LEFT PANEL
    # ─────────────────────────────────────────────────────────
    def _build_left(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        lv = QVBoxLayout(panel)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        lv.addWidget(self._title("VEHICLE COMMANDS"))
        lv.addWidget(_hsep())

        # ── STEERING card ──────────────────────────────────────
        steer_card = self._card()
        scl = QVBoxLayout(steer_card)
        scl.setContentsMargins(12, 10, 12, 12)
        scl.setSpacing(8)

        scl.addWidget(self._sect("STEERING"), alignment=Qt.AlignCenter)

        self.steer_value_label = QLabel("0°")
        self.steer_value_label.setObjectName("bigValue")
        self.steer_value_label.setAlignment(Qt.AlignCenter)
        scl.addWidget(self.steer_value_label)

        self.steer_dial = SteeringWheel()
        self.steer_dial._on_change = self._on_steer_changed
        scl.addWidget(self.steer_dial, alignment=Qt.AlignCenter)

        lv.addWidget(steer_card)

        # ── PEDALS ─────────────────────────────────────────────
        lv.addWidget(self._sect("PEDALS"), alignment=Qt.AlignCenter)

        pedal_row = QHBoxLayout()
        pedal_row.setSpacing(8)

        # Accelerator
        ac = self._card()
        acl = QVBoxLayout(ac)
        acl.setContentsMargins(10, 10, 10, 10)
        acl.setSpacing(6)
        acl.addWidget(self._sect("ACCEL"), alignment=Qt.AlignCenter)
        self.accel_slider = PedalBar(C["green"])
        self.accel_slider._on_change = self._on_accel_changed
        acl.addWidget(self.accel_slider, alignment=Qt.AlignCenter)
        self.accel_value_label = QLabel("0%")
        self.accel_value_label.setObjectName("pedalValAccel")
        self.accel_value_label.setAlignment(Qt.AlignCenter)
        acl.addWidget(self.accel_value_label)

        # Brake — orange colour
        bc = self._card()
        bcl = QVBoxLayout(bc)
        bcl.setContentsMargins(10, 10, 10, 10)
        bcl.setSpacing(6)
        bcl.addWidget(self._sect("BRAKE"), alignment=Qt.AlignCenter)
        self.brake_slider = PedalBar(C["orange"])
        self.brake_slider._on_change = self._on_brake_changed
        bcl.addWidget(self.brake_slider, alignment=Qt.AlignCenter)
        self.brake_value_label = QLabel("0%")
        self.brake_value_label.setObjectName("pedalValBrake")
        self.brake_value_label.setAlignment(Qt.AlignCenter)
        bcl.addWidget(self.brake_value_label)

        pedal_row.addWidget(ac)
        pedal_row.addWidget(bc)
        lv.addLayout(pedal_row)

        # ── SAFETY card ────────────────────────────────────────
        lv.addWidget(self._sect("SAFETY"), alignment=Qt.AlignCenter)

        safety_card = self._card()
        sfl = QVBoxLayout(safety_card)
        sfl.setContentsMargins(12, 10, 12, 12)
        sfl.setSpacing(8)

        self.emergency_btn = QPushButton("■  EMERGENCY STOP")
        self.emergency_btn.setObjectName("emergencyButton")
        self.emergency_btn.setCheckable(True)
        self.emergency_btn.setMinimumHeight(50)

        self.reset_btn = QPushButton("↺  RESET SYSTEM")
        self.reset_btn.setObjectName("resetButton")
        self.reset_btn.setMinimumHeight(42)

        self.safety_status_label = QLabel("Emergency: OFF  ·  Reset: 0")
        self.safety_status_label.setObjectName("hintLabel")
        self.safety_status_label.setAlignment(Qt.AlignCenter)

        sfl.addWidget(self.emergency_btn)
        sfl.addWidget(self.reset_btn)
        sfl.addWidget(self.safety_status_label)

        lv.addWidget(safety_card)

        hint = QLabel(
            "UDP  [steer · accel · brake · tx_time\n"
            "RTT · jitter · checksum · last_throttle\n"
            "last_brake · emergency · reset_cmd]"
        )
        hint.setObjectName("hintLabel")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        lv.addWidget(hint)

        self.scenario_info_label = QLabel(
            f"Scenario: {self.active_scenario_id if self.scenario_loaded else 'N/A'}  ·  Phase: {self.current_phase}  ·  Mode: {'AUTO' if self.use_auto_scenario else 'MANUAL'}"
        )
        self.scenario_info_label.setObjectName("hintLabel")
        self.scenario_info_label.setAlignment(Qt.AlignCenter)
        self.scenario_info_label.setWordWrap(True)
        lv.addWidget(self.scenario_info_label)

        log_text = f"Logging: ON  ·  Session: {self.session_id}  ·  Cmd Mode: {'AUTO' if self.use_auto_scenario else 'MANUAL'}"
        self.logger_info_label = QLabel(log_text)
        self.logger_info_label.setObjectName("hintLabel")
        self.logger_info_label.setAlignment(Qt.AlignCenter)
        self.logger_info_label.setWordWrap(True)
        lv.addWidget(self.logger_info_label)

        return panel

    # ─────────────────────────────────────────────────────────
    #  CENTER PANEL
    # ─────────────────────────────────────────────────────────
    def _build_center(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        lv = QVBoxLayout(panel)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)

        lv.addWidget(self._title("SIMULATION  3D  VIEW"))
        lv.addWidget(_hsep())

        # viewer — fills all available space, zero internal margins
        self.viewer_host = AspectRatioFrame(16, 9)
        self.viewer_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewer_host.setMinimumSize(760, 428)
        self.viewer_host.setContentsMargins(0, 0, 0, 0)

        # placeholder inside viewer frame
        vl = QVBoxLayout(self.viewer_host)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.viewer_placeholder = QLabel(
            "Waiting for 'Simulation 3D Viewer'…\n\n"
            "Start the Simulink simulation and\nthe app will embed it automatically."
        )
        self.viewer_placeholder.setObjectName("viewerPlaceholder")
        self.viewer_placeholder.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.viewer_placeholder)

        lv.addWidget(self.viewer_host, 1)

        # ── STATUS BAR — always visible, fixed height ──────────
        self.viewer_status_frame = QFrame()
        self.viewer_status_frame.setObjectName("statusBar")
        self.viewer_status_frame.setFixedHeight(52)
        self.viewer_status_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        sb = QHBoxLayout(self.viewer_status_frame)
        sb.setContentsMargins(24, 0, 24, 0)
        sb.setSpacing(0)

        self.mode_badge   = self._badge("MODE",   "--")
        self.fault_badge  = self._badge("FAULT",  "--")
        self.viewer_badge = self._badge("VIEWER", "WAITING")

        self.mode_value         = self.mode_badge["value"]
        self.fault_value        = self.fault_badge["value"]
        self.viewer_state_value = self.viewer_badge["value"]

        for i, b in enumerate([self.mode_badge, self.fault_badge, self.viewer_badge]):
            sb.addStretch(1)
            sb.addLayout(b["layout"])
            sb.addStretch(1)
            if i < 2:
                sb.addWidget(_vsep())

        lv.addWidget(self.viewer_status_frame)

        return panel

    # ─────────────────────────────────────────────────────────
    #  RIGHT PANEL
    # ─────────────────────────────────────────────────────────
    def _build_right(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        lv = QVBoxLayout(panel)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        lv.addWidget(self._title("SIMULINK FEEDBACK"))
        lv.addWidget(_hsep())

        # Speed card
        spd_card = self._card()
        spd_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        spvl = QVBoxLayout(spd_card)
        spvl.setContentsMargins(8, 8, 8, 8)
        spvl.setSpacing(4)
        spvl.addWidget(self._sect("SPEED"), alignment=Qt.AlignCenter)
        self.speedometer = SpeedometerWidget()
        spvl.addWidget(self.speedometer, 1)
        lv.addWidget(spd_card, 3)

        # Yaw / YawRate metric cards
        self.yaw_card      = self._metric_card("YAW",      "0.0°")
        self.yaw_rate_card = self._metric_card("YAW RATE", "0.0°/s")
        self.yaw_value      = self.yaw_card["val"]
        self.yaw_rate_value = self.yaw_rate_card["val"]
        lv.addWidget(self.yaw_card["frame"],      1)
        lv.addWidget(self.yaw_rate_card["frame"], 1)

        # Network card
        net_card = self._card()
        nvl = QVBoxLayout(net_card)
        nvl.setContentsMargins(14, 10, 14, 12)
        nvl.setSpacing(8)
        nvl.addWidget(self._sect("NETWORK STATUS"), alignment=Qt.AlignCenter)
        nvl.addWidget(_hsep())

        self.rtt_row    = self._net_row("RTT",    "0.0 ms")
        self.jitter_row = self._net_row("JITTER", "0.0 ms")
        self.link_row   = self._net_row("LINK",   "OFFLINE")

        nvl.addLayout(self.rtt_row["layout"])
        nvl.addLayout(self.jitter_row["layout"])
        nvl.addLayout(self.link_row["layout"])

        self.rtt_value        = self.rtt_row["val"]
        self.jitter_value     = self.jitter_row["val"]
        self.connection_value = self.link_row["val"]

        lv.addWidget(net_card, 1)

        return panel

    # ══════════════════════════════════════════════════════════
    #  WIDGET FACTORIES
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def _card() -> QFrame:
        f = QFrame()
        f.setObjectName("card")
        return f

    @staticmethod
    def _title(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("panelTitle")
        l.setAlignment(Qt.AlignCenter)
        return l

    @staticmethod
    def _sect(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sectionLabel")
        return l

    @staticmethod
    def _badge(label_text: str, value_text: str) -> dict:
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label_text)
        lbl.setObjectName("badgeLabel")
        lbl.setAlignment(Qt.AlignCenter)
        val = QLabel(value_text)
        val.setObjectName("badgeValue")
        val.setAlignment(Qt.AlignCenter)
        col.addWidget(lbl)
        col.addWidget(val)
        return {"layout": col, "value": val}

    @staticmethod
    def _metric_card(title: str, value: str) -> dict:
        f = QFrame()
        f.setObjectName("card")
        lv = QVBoxLayout(f)
        lv.setContentsMargins(14, 8, 14, 10)
        lv.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("sectionLabel")
        t.setAlignment(Qt.AlignCenter)
        v = QLabel(value)
        v.setObjectName("metricValue")
        v.setAlignment(Qt.AlignCenter)
        lv.addWidget(t)
        lv.addWidget(v)
        return {"frame": f, "val": v}

    @staticmethod
    def _net_row(label_text: str, value_text: str) -> dict:
        row = QHBoxLayout()
        row.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(label_text)
        lbl.setObjectName("netLabel")
        val = QLabel(value_text)
        val.setObjectName("netValue")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        return {"layout": row, "val": val}

    # ══════════════════════════════════════════════════════════
    #  SIGNAL CONNECTIONS  (unchanged)
    # ══════════════════════════════════════════════════════════
    def _connect_signals(self) -> None:
        self.emergency_btn.toggled.connect(self._on_emergency_toggled)
        self.reset_btn.clicked.connect(self._on_reset_clicked)

    # ══════════════════════════════════════════════════════════
    #  CONTROL CALLBACKS
    # ══════════════════════════════════════════════════════════
    def _on_steer_changed(self, value: int) -> None:
        self.steer_cmd_deg = value
        sign = "+" if value > 0 else ""
        self.steer_value_label.setText(f"{sign}{value}°")
        self.last_manual_input_time = time.perf_counter()
        self._send_last_command()

    def _on_accel_changed(self, value: int) -> None:
        self.accel_cmd_percent = value
        self.accel_value_label.setText(f"{value}%")
        self.last_manual_input_time = time.perf_counter()
        self._send_last_command()

    def _on_brake_changed(self, value: int) -> None:
        self.brake_cmd_percent = value
        self.brake_value_label.setText(f"{value}%")
        self.last_manual_input_time = time.perf_counter()
        self._send_last_command()

    def _on_emergency_toggled(self, checked: bool) -> None:
        self.emergency_active = 1.0 if checked else 0.0
        self.emergency_btn.setText(
            "■  EMERGENCY ACTIVE" if checked else "■  EMERGENCY STOP")
        self._update_safety_status()
        self._refresh_alert()
        self.last_manual_input_time = time.perf_counter()
        self._send_last_command()

    def _on_reset_clicked(self) -> None:
        self.reset_cmd = 1.0
        self._update_safety_status()
        self.last_manual_input_time = time.perf_counter()
        self._send_last_command()
        self.reset_pulse_timer.start(120)

    def _clear_reset_cmd(self) -> None:
        self.reset_cmd = 0.0
        self._update_safety_status()
        self._send_last_command()

    def _update_safety_status(self) -> None:
        e = "ON"  if self.emergency_active > 0.5 else "OFF"
        r = "1"   if self.reset_cmd        > 0.5 else "0"
        self.safety_status_label.setText(f"Emergency: {e}  ·  Reset: {r}")

    # ══════════════════════════════════════════════════════════
    #  ALERT OVERLAY
    # ══════════════════════════════════════════════════════════
    def _refresh_alert(self, fault_flag: bool = False) -> None:
        emergency = self.emergency_active > 0.5
        if emergency:
            self.viewer_host.set_alert(True, "EMERGENCY STOP ACTIVE")
        elif fault_flag:
            self.viewer_host.set_alert(True, "VEHICLE FAULT DETECTED")
        else:
            self.viewer_host.set_alert(False)

    # ══════════════════════════════════════════════════════════
    #  UDP / HEARTBEAT  (unchanged)
    # ══════════════════════════════════════════════════════════
    def _send_last_command(self) -> None:
        fb = self.udp_link.latest_feedback
        self.udp_link.send_commands(
            float(self.steer_cmd_deg),
            self.accel_cmd_percent / 100.0,
            self.brake_cmd_percent / 100.0,
            float(fb.get("rtt_s",    0.0)),
            float(fb.get("jitter_s", 0.0)),
            float(self.emergency_active),
            float(self.reset_cmd),
        )

    def _send_heartbeat_command(self) -> None:
        if time.perf_counter() - self.last_manual_input_time < self.manual_guard_time:
            return
        self._send_last_command()

    # ══════════════════════════════════════════════════════════
    #  FEEDBACK DISPLAY  (unchanged logic)
    # ══════════════════════════════════════════════════════════
    def _mode_id_to_text(self, mode_id: int) -> str:
        return {1: "NORMAL", 2: "SAFE_MODE", 3: "COMM_LOSS",
                4: "FAULT",  5: "EMERGENCY"}.get(mode_id, "UNKNOWN")

    def _set_mode_display(self, mode_id: int) -> None:
        color = {1: C["green"], 2: C["amber"], 3: "#fb923c",
                 4: C["red"],   5: C["red"]}.get(mode_id, C["txt1"])
        self.mode_value.setText(self._mode_id_to_text(mode_id))
        self.mode_value.setStyleSheet(
            f"color:{color}; font-size:14px; font-weight:800; letter-spacing:2px;")

    def _set_fault_display(self, fault_flag: bool) -> None:
        self.fault_value.setText("YES" if fault_flag else "NO")
        color = C["red"] if fault_flag else C["green"]
        self.fault_value.setStyleSheet(
            f"color:{color}; font-size:14px; font-weight:800; letter-spacing:2px;")

    def _set_viewer_display(self, text: str, color: str = "") -> None:
        color = color or C["txt1"]
        self.viewer_state_value.setText(text)
        self.viewer_state_value.setStyleSheet(
            f"color:{color}; font-size:14px; font-weight:800; letter-spacing:2px;")

    def _update_feedback_display(self) -> None:
        fb = self.udp_link.latest_feedback

        # Update current scenario reference
        self._get_current_reference()
        self._update_auto_command_display()
        if hasattr(self, "scenario_info_label"):
            scenario_txt = self.active_scenario_id if self.scenario_loaded else "N/A"
            mode_txt = "AUTO" if self.use_auto_scenario else "MANUAL"
            self.scenario_info_label.setText(
                f"Scenario: {scenario_txt}  ·  Phase: {self.current_phase}  ·  Mode: {mode_txt}"
            )

        speed_mps      = fb.get("speed_mps",     0.0)
        yaw_deg        = math.degrees(fb.get("yaw_rad",      0.0))
        yaw_deg        = ((yaw_deg + 180) % 360) - 180
        yaw_rate_deg_s = math.degrees(fb.get("yaw_rate_rps", 0.0))
        rtt_ms         = fb.get("rtt_ms",    0.0)
        jitter_ms      = fb.get("jitter_ms", 0.0)
        connected      = fb.get("connected", False)
        mode_id        = int(round(fb.get("mode_id",    0.0)))
        fault_flag     = bool(round(fb.get("fault_flag", 0.0)))

        self.speedometer.set_speed(speed_mps)
        self.yaw_value.setText(f"{yaw_deg:.1f}°")
        self.yaw_rate_value.setText(f"{yaw_rate_deg_s:.1f}°/s")
        self.rtt_value.setText(f"{rtt_ms:.1f} ms")
        self.jitter_value.setText(f"{jitter_ms:.1f} ms")

        if connected:
            self.connection_value.setText("ONLINE")
            self.connection_value.setStyleSheet(
                f"color:{C['green']}; font-size:13px; font-weight:800; letter-spacing:1.5px;")
        else:
            self.connection_value.setText("OFFLINE")
            self.connection_value.setStyleSheet(
                f"color:{C['red']}; font-size:13px; font-weight:800; letter-spacing:1.5px;")

        self._set_mode_display(mode_id)
        self._set_fault_display(fault_flag)
        self._refresh_alert(fault_flag)

        self._log_current_sample()

    # ══════════════════════════════════════════════════════════
    #  VIEWER EMBEDDING  (unchanged logic; resize now fills frame)
    # ══════════════════════════════════════════════════════════
    def _list_matching_viewers(self):
        matches = []
        def enum_handler(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if title and "Simulation 3D Viewer" in title:
                matches.append((hwnd, title))
        win32gui.EnumWindows(enum_handler, None)
        return matches

    def _pick_best_viewer_hwnd(self):
        matches = self._list_matching_viewers()
        return matches[0][0] if matches else None

    def _embed_viewer_native(self, hwnd: int) -> bool:
        try:
            if not win32gui.IsWindow(hwnd):
                return False

            # ── Strip ALL non-client decoration ────────────────
            style   = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

            # Remove every decoration flag
            for flag in (win32con.WS_CAPTION,
                         win32con.WS_THICKFRAME,
                         win32con.WS_MINIMIZEBOX,
                         win32con.WS_MAXIMIZEBOX,
                         win32con.WS_SYSMENU,
                         win32con.WS_POPUP,
                         win32con.WS_BORDER,
                         win32con.WS_DLGFRAME):
                style &= ~flag

            style |= win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS

            for flag in (win32con.WS_EX_DLGMODALFRAME,
                         win32con.WS_EX_CLIENTEDGE,
                         win32con.WS_EX_STATICEDGE,
                         win32con.WS_EX_WINDOWEDGE,
                         win32con.WS_EX_APPWINDOW):
                exstyle &= ~flag

            parent_hwnd = int(self.viewer_host.winId())
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE,   style)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)
            win32gui.SetParent(hwnd, parent_hwnd)

            # Force frame recalculation after style change
            import ctypes
            SWP_FLAGS = (0x0020 |   # SWP_FRAMECHANGED
                         0x0002 |   # SWP_NOMOVE
                         0x0001)    # SWP_NOSIZE
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)

            if self.viewer_placeholder is not None:
                self.viewer_placeholder.hide()

            self.viewer_host.set_embedded_hwnd(hwnd)
            self.viewer_hwnd     = hwnd
            self.viewer_embedded = True
            self._set_viewer_display("EMBEDDED", C["green"])
            return True

        except Exception:
            self._set_viewer_display("EMBED FAIL", C["red"])
            return False

    def _ensure_viewer_embedded(self) -> None:
        if (self.viewer_embedded and self.viewer_hwnd is not None
                and win32gui.IsWindow(self.viewer_hwnd)):
            self.viewer_host.set_embedded_hwnd(self.viewer_hwnd)
            self._set_viewer_display("EMBEDDED", C["green"])
            return
        hwnd = self._pick_best_viewer_hwnd()
        if hwnd is None:
            self._set_viewer_display("NOT FOUND", C["amber"])
            return
        self._embed_viewer_native(hwnd)

    def closeEvent(self, event) -> None:
        try:
            if self.session_logger is not None:
                self.session_logger.close()
        except Exception:
            pass
        self.udp_link.stop()
        super().closeEvent(event)

    # ══════════════════════════════════════════════════════════
    #  STYLESHEET  — cinematic automotive dark
    # ══════════════════════════════════════════════════════════
    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
/* ── ROOT ────────────────────────────────────────────── */
QMainWindow, QWidget {{
    background-color: {C['bg0']};
    font-family: "Segoe UI", "Roboto", "Arial", sans-serif;
    color: {C['txt1']};
    font-size: 13px;
}}

/* ── OUTER PANELS ────────────────────────────────────── */
QFrame#panel {{
    background-color: {C['bg1']};
    border: 1px solid {C['bdr']};
    border-radius: 18px;
}}

/* ── CARDS ───────────────────────────────────────────── */
QFrame#card {{
    background-color: {C['bg2']};
    border: 1px solid {C['bdr']};
    border-radius: 13px;
}}

/* ── STATUS BAR ──────────────────────────────────────── */
QFrame#statusBar {{
    background-color: {C['bg0']};
    border: 1px solid {C['bdr']};
    border-radius: 11px;
}}

/* ── VIDEO FRAME ─────────────────────────────────────── */
QFrame#videoFrame {{
    background-color: #010508;
    border: 1.5px solid {C['bdr2']};
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
}}

/* ── BASE LABELS ─────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {C['txt1']};
    font-size: 13px;
}}

QLabel#panelTitle {{
    color: {C['txt0']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 4px;
    padding: 3px 0;
}}

QLabel#sectionLabel {{
    color: {C['cyan']};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 3px;
}}

/* Steering value badge */
QLabel#bigValue {{
    color: {C['txt0']};
    font-size: 32px;
    font-weight: 300;
    background-color: {C['bg3']};
    border: 1px solid {C['bdr2']};
    border-radius: 9px;
    padding: 8px 20px;
    letter-spacing: 2px;
    min-height: 32px;
}}

/* Pedal value labels */
QLabel#pedalValAccel {{
    color: {C['green']};
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 1.5px;
}}
QLabel#pedalValBrake {{
    color: {C['orange']};
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 1.5px;
}}

/* Metric values (yaw, yaw rate) */
QLabel#metricValue {{
    color: {C['txt0']};
    font-size: 26px;
    font-weight: 300;
    letter-spacing: 1px;
}}

/* Status bar labels / values */
QLabel#badgeLabel {{
    color: {C['txt2']};
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 4px;
}}
QLabel#badgeValue {{
    color: {C['txt1']};
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 2.5px;
}}

/* Network rows */
QLabel#netLabel {{
    color: {C['txt2']};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#netValue {{
    color: {C['txt1']};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#hintLabel {{
    color: {C['txt2']};
    font-size: 9px;
    letter-spacing: 0.5px;
    line-height: 1.6;
}}

QLabel#viewerPlaceholder {{
    color: {C['txt2']};
    font-size: 14px;
    font-weight: 400;
    letter-spacing: 0.5px;
    border: none;
}}

/* ── EMERGENCY BUTTON ────────────────────────────────── */
QPushButton#emergencyButton {{
    background-color: {C['red_dim']};
    color: {C['red']};
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 2.5px;
    border: 1.5px solid #4a1212;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: center;
}}
QPushButton#emergencyButton:hover {{
    background-color: #3e1010;
    border-color: {C['red']};
    color: #ff8888;
}}
QPushButton#emergencyButton:checked {{
    background-color: #6e1010;
    border: 2px solid {C['red_hot']};
    color: #ffe0e0;
}}

/* ── RESET BUTTON ────────────────────────────────────── */
QPushButton#resetButton {{
    background-color: {C['amber_dim']};
    color: {C['amber']};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2.5px;
    border: 1.5px solid #4a3000;
    border-radius: 10px;
    padding: 8px 14px;
    text-align: center;
}}
QPushButton#resetButton:hover {{
    background-color: #2e1e00;
    border-color: {C['amber']};
    color: #ffd080;
}}
QPushButton#resetButton:pressed {{
    background-color: #3d2800;
}}
        """)