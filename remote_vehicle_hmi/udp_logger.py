import csv
import socket
from datetime import datetime
from pathlib import Path

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5005

out_dir = Path("can_logs")
out_dir.mkdir(exist_ok=True)

csv_path = out_dir / f"udp_data_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening on {LISTEN_IP}:{LISTEN_PORT}")
print(f"Saving to {csv_path}")

with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "pc_time",
        "packet_type",
        "esp_millis",
        "steer",
        "throttle",
        "brake",
        "mode_id",
        "fault_flag",
        "status_text",
        "raw_line",
    ])

    while True:
        data, addr = sock.recvfrom(1024)
        line = data.decode("utf-8", errors="ignore").strip()
        parts = line.split(",")
        pc_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        print("RAW:", line)

        try:
            packet_type = parts[0]

            if packet_type == "STATUS":
                esp_millis = parts[1] if len(parts) > 1 else ""
                status_text = ",".join(parts[2:]) if len(parts) > 2 else ""
                writer.writerow([
                    pc_time, "STATUS", esp_millis, "", "", "", "", "",
                    status_text, line
                ])
                f.flush()
                print("STATUS OK:", status_text)

            elif packet_type == "DATA":
                if len(parts) != 7:
                    raise ValueError(f"Expected 7 fields for DATA, got {len(parts)}")

                _, esp_millis, steer, throttle, brake, mode_id, fault_flag = parts
                writer.writerow([
                    pc_time, "DATA", int(esp_millis),
                    int(steer), int(throttle), int(brake),
                    int(mode_id), int(fault_flag),
                    "", line
                ])
                f.flush()
                print(
                    f"DATA OK: steer={steer} throttle={throttle} "
                    f"brake={brake} mode={mode_id} fault={fault_flag}"
                )

            else:
                writer.writerow([
                    pc_time, "UNKNOWN", "", "", "", "", "", "",
                    "", line
                ])
                f.flush()
                print("UNKNOWN PACKET:", line)

        except Exception as e:
            writer.writerow([
                pc_time, "BAD_PACKET", "", "", "", "", "", "",
                str(e), line
            ])
            f.flush()
            print("BAD PACKET:", line, "|", e)
