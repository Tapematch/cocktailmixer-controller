from nanpy import SerialManager
from nanpy.hx711 import Hx711

connection = SerialManager(device='COM3')

scale = Hx711(60, 59, connection)

print("Put nothing on the scale.")
input("Press Enter to continue")

offset = scale.averageValue()

print("Put 500g on the scale.")
input("Press Enter to continue")

averageValue = scale.averageValue()
ratio = (averageValue - offset) / 500

print("gram: " + str(averageValue))
print("ratio: " + str(ratio))

scale.setOffset(offset)
scale.setScale(ratio)

while True:
    print(scale.getGram())

