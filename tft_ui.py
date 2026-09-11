"""Shared TFT ILI9341 driver (Pi-only). Used by main.py and registration.py.

Owns GPIO24 (DC), GPIO25 (RST) and SPI0.0 at module level - importing this
module on the dev PC crashes, same as the old per-script TFT code.
"""

import time

import cv2
import numpy as np
import spidev
from gpiozero import OutputDevice

DC_PIN = OutputDevice(24)   # Pin 18 (GPIO 24)
RST_PIN = OutputDevice(25)  # Pin 22 (GPIO 25)
RST_PIN.on()                # Giu chan RESET luon o 3.3V

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 24000000
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
    RST_PIN.on()
    time.sleep(0.01)

    send_cmd(0x01); time.sleep(0.12)  # SW Reset
    send_cmd(0x11); time.sleep(0.12)  # Sleep Out

    send_cmd(0x3A); send_data(0x55)   # Mau 16-bit RGB565
    send_cmd(0x36); send_data(0x70)   # Landscape 320x240
    send_cmd(0x20)                    # Inversion OFF

    send_cmd(0xB2); send_data([0x0C, 0x0C, 0x00, 0x33, 0x33])
    send_cmd(0xB7); send_data(0x35)
    send_cmd(0xBB); send_data(0x19)
    send_cmd(0xC0); send_data(0x2C)
    send_cmd(0xC2); send_data(0x01)
    send_cmd(0xC3); send_data(0x12)
    send_cmd(0xC4); send_data(0x20)
    send_cmd(0xC6); send_data(0x0F)

    send_cmd(0x29); time.sleep(0.05)  # Display ON
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])


def render_tft(frame):
    send_cmd(0x2A); send_data([0x00, 0x00, 0x01, 0x3F])
    send_cmd(0x2B); send_data([0x00, 0x00, 0x00, 0xEF])
    send_cmd(0x2C)

    frame_u16 = frame.astype(np.uint16)
    b = frame_u16[:, :, 0] >> 3
    g = frame_u16[:, :, 1] >> 2
    r = frame_u16[:, :, 2] >> 3
    rgb565 = (r << 11) | (g << 5) | b
    send_data(rgb565.byteswap().tobytes())


def show_message(frame, lines, color=(255, 255, 255)):
    out = frame.copy()
    cv2.rectangle(out, (0, 0), (320, 240), (0, 0, 0), -1)
    y = 104 - (len(lines) - 1) * 15
    for line in lines:
        size = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
        x = max(0, (320 - size[0]) // 2)
        cv2.putText(out, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
        y += 28
    render_tft(out)
    return out


def render_capture(disp, user_name, pose_idx, pose_count, pose_name, pose_done,
                   samples_per_pose, total_done, total_target, msg, color):
    out = disp.copy()
    cv2.rectangle(out, (0, 0), (320, 58), (0, 0, 0), -1)
    cv2.putText(out, f"P{pose_idx}/{pose_count}: {pose_name}", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(out, f"{total_done}/{total_target}", (240, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(out, user_name.upper()[:20], (8, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.rectangle(out, (0, 200), (320, 240), (0, 0, 0), -1)
    cv2.putText(out, msg, (8, 221), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    bar_w = 180
    filled = int(bar_w * pose_done / samples_per_pose) if samples_per_pose else 0
    cv2.rectangle(out, (8, 228), (8 + bar_w, 236), (110, 110, 110), -1)
    cv2.rectangle(out, (8, 228), (8 + filled, 236), color, -1)
    return out


def close():
    spi.close()
    DC_PIN.close()
    RST_PIN.close()