import socket
import struct
import threading


class UDPLink:
    def __init__(
        self,
        send_ip: str = "127.0.0.1",
        send_port: int = 25000,
        recv_ip: str = "0.0.0.0",
        recv_port: int = 25001,
    ) -> None:
        self.send_addr = (send_ip, send_port)

        # Python -> Simulink
        self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Simulink -> Python
        self.rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx_sock.bind((recv_ip, recv_port))
        self.rx_sock.settimeout(0.1)

        self.running = False

        self.latest_feedback = {
            "speed_mps": 0.0,
            "yaw_rad": 0.0,
            "yaw_rate_rps": 0.0,
            "connected": False,
        }

    def send_commands(self, steer_deg: float, accel_norm: float, brake_norm: float) -> None:
        packet = struct.pack("fff", float(steer_deg), float(accel_norm), float(brake_norm))
        self.tx_sock.sendto(packet, self.send_addr)

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

                # Expect 3 float32 values: speed, yaw, yaw_rate
                if len(data) >= 12:
                    speed_mps, yaw_rad, yaw_rate_rps = struct.unpack("fff", data[:12])

                    self.latest_feedback = {
                        "speed_mps": speed_mps,
                        "yaw_rad": yaw_rad,
                        "yaw_rate_rps": yaw_rate_rps,
                        "connected": True,
                    }

            except socket.timeout:
                continue
            except Exception:
                continue