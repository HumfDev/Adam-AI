from hx711 import HX711
from ads1115_sensor import ADS1115Sensor 
import time

# --- Init HX711 ---
hx = HX711(dout=3, pd_sck=4)
hx.set_gain(128)

# Tare on startup
print("Taring...")
hx.tare()
print("Tared.")

# --- Init both ADS1115s ---
adc1 = ADS1115Sensor(i2c_id=0, sda=6, scl=7, i2c_addr=0x48)  # ADDR → GND
adc2 = ADS1115Sensor(i2c_id=0, sda=6, scl=7, i2c_addr=0x49)  # ADDR → VDD

# --- Main loop ---
while True:
    load = hx.get_value()

    a0 = adc1.read(0)
    a1 = adc1.read(1)
    b0 = adc2.read(0)
    b1 = adc2.read(1)

    print(f"{load},{a0},{a1},{b0},{b1}")
    time.sleep(0.1)