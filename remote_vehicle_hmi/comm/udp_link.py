import socket
import struct
import threading
import time


class UDPLink:
    def __init__(
        self,
        send_ip: str = "127.0.0.1",
        send_port: int = 25000,
        recv_ip: str = "0.0.0.0",
        recv_port: int = 25001,
    ) -> None:
        self.send_addr = (send_ip, send_port)

        self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx_sock.bind((recv_ip, recv_port))
        self.rx_sock.settimeout(0.1)

        self.running = False

        self.t0 = time.perf_counter()
        self.last_feedback_time = 0.0
        self.prev_rtt_s = 0.0

        # Previous command values memorized in Python
        self.prev_accel_norm = 0.0
        self.prev_brake_norm = 0.0

        self.latest_feedback = {
            "speed_mps": 0.0,
            "yaw_rad": 0.0,
            "yaw_rate_rps": 0.0,
            "connected": False,
            "echoed_tx_time": 0.0,
            "rtt_s": 0.0,
            "rtt_ms": 0.0,
            "jitter_s": 0.0,
            "jitter_ms": 0.0,
            "mode_id": 0.0,
            "fault_flag": 0.0,
        }

    def send_commands(
        self,
        steer_deg: float,
        accel_norm: float,
        brake_norm: float,
        last_rtt_s: float,
        last_jitter_s: float,
        emergency_button: float,
        reset_cmd: float,
    ) -> None:
        tx_time = time.perf_counter() - self.t0

        steer_deg = float(steer_deg)
        accel_norm = float(accel_norm)
        brake_norm = float(brake_norm)
        last_rtt_s = float(last_rtt_s)
        last_jitter_s = float(last_jitter_s)
        emergency_button = float(emergency_button)
        reset_cmd = float(reset_cmd)

        # Previous command values sent at the END of the packet
        last_throttle = float(self.prev_accel_norm)
        last_brake = float(self.prev_brake_norm)

        # Checksum aligned with current Simulink logic
        checksum = steer_deg + accel_norm + brake_norm

        # EXACT order:
        # [steer, accel, brake, tx_time, last_rtt, last_jitter, checksum,
        #  last_throttle, last_brake, emergency_button, reset_cmd]
        packet = struct.pack(
            "fffffffffff",
            steer_deg,
            accel_norm,
            brake_norm,
            float(tx_time),
            last_rtt_s,
            last_jitter_s,
            float(checksum),
            last_throttle,
            last_brake,
            emergency_button,
            reset_cmd,
        )

        self.tx_sock.sendto(packet, self.send_addr)

        # Update previous values AFTER sending
        self.prev_accel_norm = accel_norm
        self.prev_brake_norm = brake_norm

    def start_receiver(self) -> None:
        self.running = True
        thread = threading.Thread(target=self._receiver_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self.running = False
        try:
            self.rx_sock.close()
        except Exception:
            pass
        try:
            self.tx_sock.close()
        except Exception:
            pass

    def _receiver_loop(self) -> None:
        while self.running:
            try:
                data, _ = self.rx_sock.recvfrom(1024)

                # Expected feedback order:
                # [speed, yaw, yaw_rate, echoed_tx_time, mode_id, fault_flag]
                if len(data) >= 24:
                    (
                        speed_mps,
                        yaw_rad,
                        yaw_rate_rps,
                        echoed_tx_time,
                        mode_id,
                        fault_flag,
                    ) = struct.unpack("ffffff", data[:24])

                    now_rel = time.perf_counter() - self.t0

                    rtt_s = max(0.0, now_rel - echoed_tx_time)
                    rtt_ms = 1000.0 * rtt_s

                    jitter_s = abs(rtt_s - self.prev_rtt_s)
                    jitter_ms = 1000.0 * jitter_s

                    self.prev_rtt_s = rtt_s

                    self.latest_feedback = {
                        "speed_mps": speed_mps,
                        "yaw_rad": yaw_rad,
                        "yaw_rate_rps": yaw_rate_rps,
                        "connected": True,
                        "echoed_tx_time": echoed_tx_time,
                        "rtt_s": rtt_s,
                        "rtt_ms": rtt_ms,
                        "jitter_s": jitter_s,
                        "jitter_ms": jitter_ms,
                        "mode_id": mode_id,
                        "fault_flag": fault_flag,
                    }

                    self.last_feedback_time = time.perf_counter()

            except socket.timeout:
                if time.perf_counter() - self.last_feedback_time > 0.5:
                    self.latest_feedback["connected"] = False
                continue

            except OSError:
                break

            except Exception:
                continue