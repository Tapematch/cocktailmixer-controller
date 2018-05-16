from nanpy import (ArduinoApi, SerialManager)
from nanpy.hx711 import Hx711

import configuration

connection = SerialManager(device='COM3')
arduino = ArduinoApi(connection=connection)

scale = Hx711(60, 59, connection)
scale.setOffset(8332950)
scale.setScale(440)

while True:
    print(scale.getGram())
