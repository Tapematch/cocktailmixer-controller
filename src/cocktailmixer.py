from datetime import datetime
from time import sleep

from MeteorClient import MeteorClient
from nanpy import (ArduinoApi, SerialManager)
from nanpy.hx711 import Hx711

import configuration

connection = SerialManager(device='COM3')
arduino = ArduinoApi(connection=connection)

arduino.pinMode(configuration.PUMP_PIN, arduino.OUTPUT)
for pin in configuration.VALVE_PINS:
    arduino.pinMode(pin, arduino.OUTPUT)

scale = Hx711(60, 59, connection)
scale.setOffset(8332950)
scale.setScale(440)

client = MeteorClient(configuration.SERVER)


def write_log(type, message):
    client.insert('log', {'datetime': datetime.now(), 'source': 'mixer', 'type': type, 'message': message})


def update_callback(error, data):
    if error:
        write_log('error', 'Error on update: {}'.format(error))


def subscription_callback(error):
    if error:
        write_log('error', 'Error on subscription: {}'.format(error))


def connected():
    write_log('debug', 'Mixer connected to Server')


def closed(code, reason):
    write_log('warning', 'Mixer to Server connection closed with code {} because of reason {}'.format(code, reason))


def reconnected():
    write_log('debug', 'Mixer reconnected to Server')


def subscribed(subscription):
    write_log('debug', 'Mixer subscribed to {}'.format(subscription))


def unsubscribed(subscription):
    write_log('debug', 'Mixer unsubscribed form {}'.format(subscription))


client.on('connected', connected)
client.on('socket_closed', closed)
client.on('reconnected', reconnected)
client.on('subscribed', subscribed)
client.on('unsubscribed', unsubscribed)

client.connect()

client.subscribe('queue', callback=subscription_callback)
client.subscribe('configuration', callback=subscription_callback)
client.subscribe('log', callback=subscription_callback)


def start_pump(valve):
    valvepin = configuration.VALVE_PINS[valve]
    arduino.digitalWrite(valvepin, arduino.HIGH)
    arduino.digitalWrite(configuration.PUMP_PIN, arduino.HIGH)


def stop_pump(valve):
    valvepin = configuration.VALVE_PINS[valve]
    arduino.digitalWrite(configuration.PUMP_PIN, arduino.LOW)
    arduino.digitalWrite(valvepin, arduino.LOW)


def calculate_progress(progress, mixedamount, totalamount):
    currentprogress = int(mixedamount / totalamount * 100)
    if currentprogress != progress:
        queueItem['progress'] = currentprogress
        client.update('queue', {'_id': queueItem['_id']}, queueItem)
    return currentprogress


def check_glass(gram):
    return gram >= configuration.GLASS_WEIGHT


def calculate_run_on_weight(mixedpartamount, mixedcocktailamount, totalcocktailamount, progress, partamount, valve):
    # measure weight richt after pump stopped
    startweight = scale.getGram()

    # cancel if glass is raised or user canceled
    if not check_glass(startweight) or queueItem['status'] == 'canceled':
        return False

    secondweight = startweight
    while True:
        firstweight = secondweight
        secondweight = scale.getGram()
        # cancel if glass was raised or user canceled
        if not check_glass(secondweight) or secondweight < startweight:
            write_log('warning', 'Glass was lifted while waiting for run on weight for valve {}'.format(valve))
            return False
        if queueItem['status'] == 'canceled':
            write_log('warning',
                      'Mixing was canceled by user while waiting for run on weight for valve {}'.format(valve))
            return False

        # if weight did not raise between two readings, stop waiting
        if secondweight < firstweight + 0.1:
            break

        # calculate and save progress of 100%, but only if it didn´t raise above the target weight
        mixedamount = mixedcocktailamount + mixedpartamount + (firstweight - startweight)
        if mixedamount <= mixedcocktailamount + partamount:
            progress = calculate_progress(progress, mixedamount, totalcocktailamount)

    # save weight that runs on after the pump stopped for this valve
    if secondweight - startweight >= 0:
        configuration.RUN_ON_WEIGHT[valve] = secondweight - startweight
        write_log('debug', 'Set run-on-weight to {:.2f}g for valve {}'.format(configuration.RUN_ON_WEIGHT[valve], valve))
    return True


def wait_for_ingredient_refill(queueItem, valve):
    stop_pump(valve)
    update_status(queueItem, 'error')

    write_log('warning', 'Ingredient at valve {} empty'.format(valve))

    mixerstatus = client.find_one('configuration', selector={'name': 'status'})
    mixerstatus['value'] = {'type': 'ingredient_empty', 'valve': valve}
    client.update('configuration', selector={'_id': mixerstatus['_id']}, modifier=mixerstatus, callback=update_callback)

    while mixerstatus['value']['type'] == 'ingredient_empty':
        if not check_glass(scale.getGram()):
            write_log('warning', 'Glass was lifted while refilling ingredient for valve {}'.format(valve))
            return False
        if queueItem['status'] == 'canceled':
            write_log('warning', 'Mixing was canceled by user while refilling ingredient for valve {}'.format(valve))
            return False
    update_status(queueItem, 'mixing')
    start_pump(valve)
    return True


def mix_cocktail(queueItem):
    completed = True
    cocktail = client.find_one('cocktails', selector={'_id': queueItem['cocktailId']})
    write_log('debug', 'Mixing Cocktail {}'.format(cocktail['name']))

    totalcocktailamount = 0
    for part in cocktail['recipe']:
        totalcocktailamount = totalcocktailamount + part['amount']

    progress = 0
    mixedcocktailamount = 0
    for part in cocktail['recipe']:
        scaleTare = scale.getGram()

        ingredient = client.find_one('ingredients', selector={'_id': part['ingredientId']})
        valve = ingredient['pump'] - 1

        write_log('debug', 'Mixing {}ml of Ingredient {}'.format(part['amount'], ingredient['name']))

        # write current part to queue
        queueItem['current'] = part
        client.update('queue', {'_id': queueItem['_id']}, queueItem, callback=update_callback)

        start_pump(valve)

        # subtract run on weight of last time from amount of part
        amount = part['amount'] - configuration.RUN_ON_WEIGHT[valve]
        if amount < 1:
            amount = 1
        mixedpartamount = 0
        time = datetime.now()
        while mixedpartamount < amount:
            # calculate and save progress of 100%
            progress = calculate_progress(progress, mixedcocktailamount + mixedpartamount, totalcocktailamount)
            weight = scale.getGram()

            # if weight did not raise since configured time, ingredient is empty
            # if ingredient is empty, wait until status is reset
            if mixedpartamount + configuration.CHECK_INGREDIENT_WEIGHT > weight - scaleTare:
                newtime = datetime.now()
                seconds = (newtime - time).total_seconds()
                if seconds >= configuration.CHECK_INGREDIENT_TIME:
                    completed = wait_for_ingredient_refill(queueItem, valve)
                    time = datetime.now()
            else:
                # reset time only if weight increased
                time = datetime.now()

            # cancel if glass was raised or user canceled
            if not check_glass(weight):
                write_log('warning', 'Glass was lifted while mixing cocktail')
                return False
            if queueItem['status'] == 'canceled':
                write_log('warning', 'Mixing was canceled by user')
                return False

            mixedpartamount = weight - scaleTare
            if not completed:
                break

        # important! always stop pump
        stop_pump(valve)

        if completed:
            # wait until liquid stops running and save the weight that ran on for next time
            if calculate_run_on_weight(mixedpartamount, mixedcocktailamount, totalcocktailamount, progress,
                                       part['amount'], valve):
                mixedcocktailamount = mixedcocktailamount + part['amount']
            else:
                completed = False
                break
        else:
            break

    # show progress = 100%
    if completed:
        calculate_progress(0, totalcocktailamount, totalcocktailamount)
        write_log('debug', 'Mixing successfully completed')
    return completed


def update_status(queueItem, status):
    queueItem['status'] = status
    client.update('queue', {'_id': queueItem['_id']}, queueItem, callback=update_callback)


write_log('debug', 'Cocktailmixer started')

# continue forever
while True:
    # find next item in queue
    queueItem = client.find_one('queue', selector={'status': 'next'})

    if not (queueItem is None):
        write_log('debug', 'Queue Item loaded')
        update_status(queueItem, 'loaded')

        # wait for user to start mixing
        while queueItem['status'] != 'start':
            sleep(0.1)

        # wait until user puts glass on scale
        if not check_glass(scale.getGram()):
            update_status(queueItem, 'waitingforglass')
            while not check_glass(scale.getGram()):
                sleep(0.1)
            sleep(0.5)

        update_status(queueItem, 'mixing')

        completed = mix_cocktail(queueItem)

        if completed:
            update_status(queueItem, 'completed')
        else:
            update_status(queueItem, 'canceled')
            sleep(3)

        # wait until user removes glass
        while check_glass(scale.getGram()):
            sleep(0.1)

        update_status(queueItem, 'removed')

client.unsubscribe('queue')
client.unsubscribe('configuration')
client.unsubscribe('log')
