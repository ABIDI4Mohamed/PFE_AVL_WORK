import serial
import time

PORT = "COM3"
BAUDRATE = 115200

print("Début script")
ser = serial.Serial(PORT, BAUDRATE, timeout=2)

time.sleep(3)  # laisse le temps à l'ESP8266 de redémarrer si ouverture du port = reset
ser.reset_input_buffer()

message = "HELLO\n"
ser.write(message.encode("utf-8"))
print("Message envoyé :", message.strip())

time.sleep(1)

response = ser.read_all().decode("utf-8", errors="ignore")
print("Réponse ESP8266 :")
print(response)

ser.close()
print("Fin script")