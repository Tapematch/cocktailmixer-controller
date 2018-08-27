from nanpy import SerialManager
from nanpy.RGBLED import RGBLED

connection = SerialManager(device='COM3')
led = RGBLED(2, 3, 4, connection)

led.addLED(5, 6, 7)
led.addLED(8, 9, 10)

led.setColor(255,0,0)
led.fadeToColor(0,255,255,2000)

while True:
    led.update()