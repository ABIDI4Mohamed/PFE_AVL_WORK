import math
import time
import win32gui
import win32con

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (
    QDial,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSlider,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from comm.udp_link import UDPLink


class AspectRatioFrame(QFrame):
    def __init__(self, aspect_w=16, aspect_h=9, parent=None):
        super().__init__(parent)
        self.setObjectName("videoFrame")
        self.aspect_w = aspect_w
        self.aspect_h = aspect_h
        self.embedded_hwnd = None

    def set_embedded_hwnd(self, hwnd: int):
        self.embedded_hwnd = hwnd
        self._resize_embedded()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_embedded()

    def _resize_embedded(self):
        if not self.embedded_hwnd or not win32gui.IsWindow(self.embedded_hwnd):
            return

        host_w = max(1, self.width())
        host_h = max(1, self.height())

        target_ratio = self.aspect_w / self.aspect_h
        current_ratio = host_w / host_h

        crop_factor = 1.06

        if current_ratio > target_ratio:
            h = int(host_h * crop_factor)
            w = int(h * target_ratio)
            x = (host_w - w) // 2
            y = (host_h - h) // 2
        else:
            w = int(host_w * crop_factor)
            h = int(w / target_ratio)
            x = (host_w - w) // 2
            y = (host_h - h) // 2

        try:
            win32gui.MoveWindow(self.embedded_hwnd, x, y, w, h, True)
        except Exception:
            pass


class SpeedometerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.speed_kmh = 0.0
        self.speed_mps = 0.0
        self.max_speed_kmh = 220.0
        self.setMinimumSize(260, 300)
        self.setObjectName("speedometer")

    def set_speed(self, speed_mps: float):
        self.speed_mps = max(0.0, speed_mps)
        self.speed_kmh = self.speed_mps * 3.6
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(14, 14, -14, -14)

        cx = rect.center().x()
        cy = rect.center().y() + 42
        radius = min(rect.width(), rect.height()) * 0.34

        start_deg = 225
        span_deg = 270

        arc_rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        bg_pen = QPen(QColor("#263754"), 10)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(arc_rect, start_deg * 16, -span_deg * 16)

        ratio = min(max(self.speed_kmh / self.max_speed_kmh, 0.0), 1.0)

        prog_pen = QPen(QColor("#67b3ff"), 8)
        prog_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(prog_pen)
        painter.drawArc(arc_rect, start_deg * 16, int(-span_deg * ratio * 16))

        total_ticks = 28
        for i in range(total_ticks + 1):
            tick_ratio = i / total_ticks
            a_deg = start_deg - span_deg * tick_ratio
            a = math.radians(a_deg)

            is_major = (i % 4 == 0)
            outer_r = radius
            inner_r = radius - (18 if is_major else 10)

            p1 = QPointF(cx + inner_r * math.cos(a), cy - inner_r * math.sin(a))
            p2 = QPointF(cx + outer_r * math.cos(a), cy - outer_r * math.sin(a))

            pen = QPen(QColor("#e7f0ff") if is_major else QColor("#7e92b4"), 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(p1, p2)

        painter.setPen(QColor("#e7f0ff"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))

        label_values = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 220]
        for value in label_values:
            label_ratio = value / self.max_speed_kmh
            a_deg = start_deg - span_deg * label_ratio
            a = math.radians(a_deg)

            text_r = radius - 24
            tx = cx + text_r * math.cos(a)
            ty = cy - text_r * math.sin(a)

            text_rect = QRectF(tx - 16, ty - 10, 32, 20)
            painter.drawText(text_rect, Qt.AlignCenter, str(value))

        needle_deg = start_deg - span_deg * ratio
        na = math.radians(needle_deg)

        needle_len = radius - 24
        needle_end = QPointF(cx + needle_len * math.cos(na), cy - needle_len * math.sin(na))

        needle_pen = QPen(QColor("#ffffff"), 4)
        needle_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(needle_pen)
        painter.drawLine(QPointF(cx, cy), needle_end)

        painter.setBrush(QColor("#0e1a2b"))
        painter.setPen(QPen(QColor("#22324d"), 2))
        painter.drawEllipse(QPointF(cx, cy), 14, 14)

        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 20, QFont.Bold))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 2, rect.width(), 34),
            Qt.AlignCenter,
            f"{self.speed_kmh:.1f}"
        )

        painter.setPen(QColor("#8ec5ff"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 30, rect.width(), 20),
            Qt.AlignCenter,
            "km/h"
        )

        painter.setPen(QColor("#6f8fbe"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 50, rect.width(), 18),
            Qt.AlignCenter,
            f"{self.speed_mps:.1f} m/s"
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vehicle Command HMI")
        self.resize(1560, 880)

        self.steer_cmd_deg = 0
        self.accel_cmd_percent = 0
        self.brake_cmd_percent = 0

        self.last_manual_input_time = 0.0
        self.manual_guard_time = 0.05   # 50 ms
        self.heartbeat_period_ms = 20   # 50 Hz

        self.udp_link = UDPLink(send_port=25000, recv_port=25001)
        self.udp_link.start_receiver()

        self.viewer_hwnd = None
        self.viewer_embedded = False

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

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        root_layout.addWidget(self._build_controls_panel(), 2)
        root_layout.addWidget(self._build_visual_panel(), 6)
        root_layout.addWidget(self._build_feedback_panel(), 3)

    def _build_controls_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(16)

        title = QLabel("VEHICLE COMMANDS")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.steer_value_label = QLabel("Steering: 0°")
        self.steer_value_label.setObjectName("bigValue")
        self.steer_value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.steer_value_label)

        self.steer_dial = QDial()
        self.steer_dial.setRange(-90, 90)
        self.steer_dial.setValue(0)
        self.steer_dial.setNotchesVisible(True)
        self.steer_dial.setWrapping(False)
        self.steer_dial.setTracking(True)
        self.steer_dial.setFixedSize(210, 210)
        layout.addWidget(self.steer_dial, alignment=Qt.AlignCenter)

        pedal_row = QHBoxLayout()
        pedal_row.setSpacing(18)

        accel_box = QFrame()
        accel_box.setObjectName("subPanel")
        accel_layout = QVBoxLayout(accel_box)
        accel_layout.setSpacing(10)

        accel_title = QLabel("ACCELERATOR")
        accel_title.setObjectName("sectionTitle")
        accel_title.setAlignment(Qt.AlignCenter)
        accel_layout.addWidget(accel_title)

        self.accel_slider = QSlider(Qt.Vertical)
        self.accel_slider.setObjectName("accelSlider")
        self.accel_slider.setRange(0, 100)
        self.accel_slider.setValue(0)
        self.accel_slider.setTracking(True)
        self.accel_slider.setFixedHeight(220)
        accel_layout.addWidget(self.accel_slider, alignment=Qt.AlignCenter)

        self.accel_value_label = QLabel("0%")
        self.accel_value_label.setObjectName("pedalValue")
        self.accel_value_label.setAlignment(Qt.AlignCenter)
        accel_layout.addWidget(self.accel_value_label)

        brake_box = QFrame()
        brake_box.setObjectName("subPanel")
        brake_layout = QVBoxLayout(brake_box)
        brake_layout.setSpacing(10)

        brake_title = QLabel("BRAKE")
        brake_title.setObjectName("sectionTitle")
        brake_title.setAlignment(Qt.AlignCenter)
        brake_layout.addWidget(brake_title)

        self.brake_slider = QSlider(Qt.Vertical)
        self.brake_slider.setObjectName("brakeSlider")
        self.brake_slider.setRange(0, 100)
        self.brake_slider.setValue(0)
        self.brake_slider.setTracking(True)
        self.brake_slider.setFixedHeight(220)
        brake_layout.addWidget(self.brake_slider, alignment=Qt.AlignCenter)

        self.brake_value_label = QLabel("0%")
        self.brake_value_label.setObjectName("pedalValue")
        self.brake_value_label.setAlignment(Qt.AlignCenter)
        brake_layout.addWidget(self.brake_value_label)

        pedal_row.addWidget(accel_box)
        pedal_row.addWidget(brake_box)
        layout.addLayout(pedal_row)

        hint = QLabel("Sending steer / accel / brake to Simulink via UDP")
        hint.setObjectName("hintLabel")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        return panel

    def _build_visual_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        title = QLabel("SIMULATION 3D VIEW")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.viewer_host = AspectRatioFrame(16, 9)
        self.viewer_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewer_host.setMinimumSize(1020, 574)

        host_layout = QVBoxLayout(self.viewer_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.viewer_placeholder = QLabel(
            "Waiting for 'Simulation 3D Viewer'...\n\n"
            "Start the Simulink simulation and the app will embed it."
        )
        self.viewer_placeholder.setObjectName("viewerPlaceholder")
        self.viewer_placeholder.setAlignment(Qt.AlignCenter)
        host_layout.addWidget(self.viewer_placeholder)

        layout.addWidget(self.viewer_host, 1)

        self.viewer_info = QLabel("Simulation 3D Viewer embedded")
        self.viewer_info.setObjectName("bottomInfo")
        self.viewer_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.viewer_info)

        return panel

    def _build_feedback_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(14)

        title = QLabel("SIMULINK FEEDBACK")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        speed_card = QFrame()
        speed_card.setObjectName("speedCard")
        speed_card.setMinimumHeight(420)

        speed_layout = QVBoxLayout(speed_card)
        speed_layout.setContentsMargins(10, 10, 10, 10)
        speed_layout.setSpacing(8)

        speed_title = QLabel("SPEED")
        speed_title.setObjectName("metricTitle")
        speed_title.setAlignment(Qt.AlignCenter)
        speed_layout.addWidget(speed_title)

        self.speedometer = SpeedometerWidget()
        speed_layout.addWidget(self.speedometer)

        layout.addWidget(speed_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.yaw_card = self._make_metric_card("YAW", "0.0°")
        self.yaw_rate_card = self._make_metric_card("YAW RATE", "0.0°/s")
        self.connection_card = self._make_metric_card("LINK", "OFFLINE")

        self.yaw_value = self.yaw_card["value"]
        self.yaw_rate_value = self.yaw_rate_card["value"]
        self.connection_value = self.connection_card["value"]

        grid.addWidget(self.yaw_card["frame"], 0, 0)
        grid.addWidget(self.yaw_rate_card["frame"], 1, 0)
        grid.addWidget(self.connection_card["frame"], 2, 0)

        layout.addLayout(grid)
        layout.addStretch()

        return panel

    def _make_metric_card(self, title: str, value: str) -> dict:
        frame = QFrame()
        frame.setObjectName("metricCard")
        layout = QVBoxLayout(frame)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        title_label.setAlignment(Qt.AlignCenter)

        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return {"frame": frame, "value": value_label}

    def _connect_signals(self) -> None:
        self.steer_dial.valueChanged.connect(self._on_controls_changed)
        self.accel_slider.valueChanged.connect(self._on_controls_changed)
        self.brake_slider.valueChanged.connect(self._on_controls_changed)

    def _on_controls_changed(self) -> None:
        self.steer_cmd_deg = self.steer_dial.value()
        self.accel_cmd_percent = self.accel_slider.value()
        self.brake_cmd_percent = self.brake_slider.value()

        self.steer_value_label.setText(f"Steering: {self.steer_cmd_deg}°")
        self.accel_value_label.setText(f"{self.accel_cmd_percent}%")
        self.brake_value_label.setText(f"{self.brake_cmd_percent}%")

        self.last_manual_input_time = time.perf_counter()

        # Immediate priority for manual command
        self._send_last_command()

    def _send_last_command(self) -> None:
        # Compatible with your current udp_link.py that still adds tx_time internally
        self.udp_link.send_commands(
            float(self.steer_cmd_deg),
            self.accel_cmd_percent / 100.0,
            self.brake_cmd_percent / 100.0,
        )

    def _send_heartbeat_command(self) -> None:
        now = time.perf_counter()

        # If a fresh manual action just happened, skip this heartbeat
        if now - self.last_manual_input_time < self.manual_guard_time:
            return

        self._send_last_command()

    def _update_feedback_display(self) -> None:
        fb = self.udp_link.latest_feedback

        speed_mps = fb["speed_mps"]
        yaw_deg = math.degrees(fb["yaw_rad"])
        yaw_deg = ((yaw_deg + 180) % 360) - 180
        yaw_rate_deg_s = math.degrees(fb["yaw_rate_rps"])

        self.speedometer.set_speed(speed_mps)
        self.yaw_value.setText(f"{yaw_deg:.1f}°")
        self.yaw_rate_value.setText(f"{yaw_rate_deg_s:.1f}°/s")
        self.connection_value.setText("ONLINE" if fb["connected"] else "OFFLINE")

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
        if not matches:
            return None
        return matches[0][0]

    def _embed_viewer_native(self, hwnd: int) -> bool:
        try:
            if not win32gui.IsWindow(hwnd):
                return False

            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

            style &= ~win32con.WS_CAPTION
            style &= ~win32con.WS_THICKFRAME
            style &= ~win32con.WS_MINIMIZEBOX
            style &= ~win32con.WS_MAXIMIZEBOX
            style &= ~win32con.WS_SYSMENU
            style &= ~win32con.WS_POPUP
            style |= win32con.WS_CHILD

            exstyle &= ~win32con.WS_EX_DLGMODALFRAME
            exstyle &= ~win32con.WS_EX_CLIENTEDGE
            exstyle &= ~win32con.WS_EX_STATICEDGE
            exstyle &= ~win32con.WS_EX_WINDOWEDGE

            parent_hwnd = int(self.viewer_host.winId())

            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)
            win32gui.SetParent(hwnd, parent_hwnd)

            if self.viewer_placeholder is not None:
                self.viewer_placeholder.hide()

            self.viewer_host.set_embedded_hwnd(hwnd)
            self.viewer_hwnd = hwnd
            self.viewer_embedded = True
            self.viewer_info.setText("Simulation 3D Viewer embedded")
            return True
        except Exception as e:
            self.viewer_info.setText(f"Embed failed: {e}")
            return False

    def _ensure_viewer_embedded(self) -> None:
        if self.viewer_embedded and self.viewer_hwnd is not None and win32gui.IsWindow(self.viewer_hwnd):
            self.viewer_host.set_embedded_hwnd(self.viewer_hwnd)
            return

        hwnd = self._pick_best_viewer_hwnd()
        if hwnd is None:
            self.viewer_info.setText("Simulation 3D Viewer not found yet")
            return

        self._embed_viewer_native(hwnd)

    def closeEvent(self, event) -> None:
        self.udp_link.stop()
        super().closeEvent(event)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #08111f;
            }

            QFrame#panel {
                background-color: #101b2d;
                border: 1px solid #23314d;
                border-radius: 18px;
            }

            QFrame#subPanel {
                background-color: #0d1626;
                border: 1px solid #263754;
                border-radius: 14px;
                padding: 8px;
            }

            QFrame#metricCard, QFrame#speedCard {
                background-color: #0d1626;
                border: 1px solid #2a3c5d;
                border-radius: 16px;
                padding: 8px;
            }

            QLabel {
                color: #d9e7ff;
                font-size: 15px;
            }

            QLabel#panelTitle {
                color: #f4f8ff;
                font-size: 18px;
                font-weight: 800;
                padding-top: 4px;
                padding-bottom: 2px;
            }

            QLabel#bigValue {
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                background-color: #0d1626;
                border: 1px solid #243754;
                border-radius: 16px;
                padding: 12px;
            }

            QLabel#sectionTitle {
                color: #8ec5ff;
                font-size: 14px;
                font-weight: 700;
            }

            QLabel#pedalValue {
                color: #ffffff;
                font-size: 20px;
                font-weight: 700;
            }

            QLabel#metricTitle {
                color: #8ec5ff;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#metricValue {
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
            }

            QLabel#hintLabel {
                color: #7fa3d6;
                font-size: 13px;
            }

            QLabel#bottomInfo {
                color: #6f8fbe;
                font-size: 12px;
                padding-top: 2px;
                padding-bottom: 0px;
            }

            QFrame#videoFrame {
                background-color: #081726;
                border: 2px solid #223b63;
                border-radius: 14px;
            }

            QLabel#viewerPlaceholder {
                color: #7fa3d6;
                font-size: 17px;
                font-weight: 600;
                padding: 18px;
            }

            QDial {
                background-color: #0d1626;
            }

            QSlider::groove:vertical {
                width: 14px;
                background: #20314d;
                border-radius: 7px;
            }

            QSlider#accelSlider::sub-page:vertical {
                background: #1db954;
                border-radius: 7px;
            }

            QSlider#accelSlider::handle:vertical {
                background: #d1fae5;
                height: 20px;
                margin: -3px;
                border-radius: 7px;
                border: 1px solid #166534;
            }

            QSlider#brakeSlider::sub-page:vertical {
                background: #e53935;
                border-radius: 7px;
            }

            QSlider#brakeSlider::handle:vertical {
                background: #ffe4e6;
                height: 20px;
                margin: -3px;
                border-radius: 7px;
                border: 1px solid #991b1b;
            }
        """)