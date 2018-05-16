SERVER = 'ws://127.0.0.1:3000/websocket'

# pins
VALVE_PINS = [40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53]
PUMP_PIN = 14
LOAD_CELL_SCK_PIN = 'A5'
LOAD_CELL_DOUT_PIN = 'A6'
ENCODER_PINS = [20, 21]
BUTTON_PIN = 'A4'
LED_R_PINS = [2, 5, 8]
LED_G_PINS = [3, 6, 9]
LED_B_PINS = [4, 7, 10]

# the mixer will start with these and save the real weights after first use
RUN_ON_WEIGHT = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]

# min weight of glass
GLASS_WEIGHT = 5

# weight and time for checking, if ingredient is empty
CHECK_INGREDIENT_TIME = 4 #seconds
CHECK_INGREDIENT_WEIGHT = 2 #ml