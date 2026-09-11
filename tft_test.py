import glob
import spidev
import sys
import time
from gpiozero import OutputDevice

# Test TFT: gui cac mau doi sang de kiem tra duong SPI + init.
# Chay tren Pi:
#   python tft_test.py            -> SPI CE0 (chan 24), nhu main.py
#   python tft_test.py 1          -> SPI CE1 (chan 26) - thu khi CS noi vao CE1
#   python tft_test.py 0 slow     -> CE0 + SPI 1MHz
#
# Pha 1: init day du @24MHz -> DO, XANH LA, XANH DUONG (moi mau 2s)
# Pha 2: init toi thieu @24MHz -> XANH LA (2s)
# Pha 3: init day du @1MHz -> DO (2s)
# Hay nhin TFT va bao lai mau nao hien ra duoc o pha nao.

CE = 0
SPEED = 24000000
if len(sys.argv) >= 2:
    CE = int(sys.argv[1])
if len(sys.argv) >= 3 and sys.argv[2] == "slow":
    SPEED = 1000000

print("spidev co san:", glob.glob("/dev/spidev*"))
print(f"Dung bus=0 device={CE}, speed={SPEED}")

try:
    DC_PIN = OutputDevice(24)
    RST_PIN = OutputDevice(25)
    RST_PIN.on()
except Exception as exc:
    print("KHONG MO DUOC GPIO:", exc)
    sys.exit(1)

spi = spidev.SpiDev()
try:
    spi.open(0, CE)
except OSError as exc:
    print(f"KHONG MO DUOC SPI (0,{CE}):", exc)
    print("Co main.py/fina.service dang chay? sudo systemctl stop fina")
    sys.exit(1)
spi.max_speed_hz = SPEED
spi.mode = 0


def send_cmd(cmd):
    DC_PIN.off()
    spi.writebytes([cmd])


def send_data(data):
    DC_PIN.on()
    if isinstance(data, int):
        spi.writebytes([data])
    elif isinstance(data, list):
        spi.writebytes(data)
    else:
        for i in range(0, len(data), 4096):
            spi.writebytes2(data[i:i + 4096])


def init_tft():
    send_cmd(0x01); time.sleep(0.12)
    send_cmd(0x11); time.sleep(0.12)
    send_cmd(0x3A); send_data(0x55)
    send_cmd(0x36); send_data(0x70)
    send_cmd(0x20)
    send_cmd(0xB2); send_data([0x0C, 0x0C, 0x00, 0x33, 0x33])
    send_cmd(0xB7); send_data(0x35)
    send_cmd(0xBB); send_data(0x19)
    send_cmd(0xC0); send_data(0x2C)
    send_cmd(0xC2); send_data(0x01)
    send_cmd(0xC3); send_data(0x12)
    send_cmd(0xC4); send_data(0x20)
    send_cmd(0xC6); send_data(0x0F)
    send_cmd(0x29); time.sleep(0.05)


def init_min():
    send_cmd(0x01); time.sleep(0.12)
    send_cmd(0x11); time.sleep(0.12)
    send_cmd(0x3A); send_data(0x55)
    send_cmd(0x36); send_data(0x70)
    send_cmd(0x20)
    send_cmd(0x29); time.sleep(0.05)


def fill(color565, seconds=2):
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])
    send_cmd(0x2C)
    lo = color565 & 0xFF
    hi = (color565 >> 8) & 0xFF
    chunk = bytes([hi, lo]) * 4096
    total = 320 * 240
    sent = 0
    while sent < total:
        n = min(4096, total - sent)
        spi.writebytes2(chunk[:n * 2])
        sent += n
    time.sleep(seconds)


RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F

print("Pha 1: init day du -> RED/GREEN/BLUE (moi mau 2s)")
init_tft()
fill(RED)
print("  -> da gui mau DO")
fill(GREEN)
print("  -> da gui mau XANH LA")
fill(BLUE)
print("  -> da gui mau XANH DUONG")

print("Pha 2: init toi thieu -> XANH LA")
init_min()
fill(GREEN)
print("  -> da gui")

print("Pha 3: init day du, SPI 1MHz -> DO")
spi.max_speed_hz = 1000000
init_tft()
fill(RED)
print("  -> da gui")

print("Xong. Neu tat ca deu trang/den -> loi phan cung (day noi/nguon/panel).")