#!/usr/bin/env python
# coding: utf8

from datetime import datetime
from time import sleep

import sys
from MeteorClient import MeteorClient
from nanpy import (ArduinoApi, SerialManager)
from nanpy.hx711 import Hx711
from nanpy.RGBLED import RGBLED

import configuration

connection = SerialManager(device=configuration.SERIAL_PORT)

led = RGBLED(configuration.LED_R_PINS[0], configuration.LED_G_PINS[0], configuration.LED_B_PINS[0], connection)
for i in range(1, len(configuration.LED_R_PINS)):
    led.addLED(configuration.LED_R_PINS[i], configuration.LED_G_PINS[i], configuration.LED_B_PINS[i])

led.setColor(0, 0, 255)

arduino = ArduinoApi(connection=connection)
arduino.pinMode(configuration.PUMP_PIN, arduino.OUTPUT)
for pin in configuration.VALVE_PINS:
    arduino.pinMode(pin, arduino.OUTPUT)

scale = Hx711(configuration.LOAD_CELL_DOUT_PIN, configuration.LOAD_CELL_SCK_PIN, connection)

client = MeteorClient(configuration.SERVER)


def write_log(type, message):
    client.call('log.insert', [type, message])


def update_callback(error, data):
    if error:
        write_log('error', 'Error on update: {}'.format(error))


def insert_callback(error, data):
    if error:
        write_log('error', 'Error on insert: {}'.format(error))


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
    write_log('debug', 'Mixer unsubscribed from {}'.format(subscription))


def logged_in(data):
    write_log('debug', 'Mixer successfully logged in')
    print(data)


def logged_out():
    write_log('debug', 'Mixer logged out')


def callback_function(error, result):
    if error:
        write_log('error', 'Error on method call: {}'.format(error))


client.on('connected', connected)
client.on('socket_closed', closed)
client.on('reconnected', reconnected)
client.on('subscribed', subscribed)
client.on('unsubscribed', unsubscribed)
client.on('logged_in', logged_in)
client.on('logged_out', logged_out)

client.connect()
client.logout()
client.login(configuration.USER, configuration.PASSWORD)

client.subscribe('configuration', callback=subscription_callback)
client.subscribe('queue', callback=subscription_callback)
client.subscribe('ingredients', callback=subscription_callback)
client.subscribe('cocktails', callback=subscription_callback)

sleep(1)

mixer_configuration = client.find_one('configuration', selector={"name": "mixer"})
mixer_status = client.find_one('configuration', selector={'name': 'status'})


def start_pump(valve):
    valvepin = configuration.VALVE_PINS[valve]
    arduino.digitalWrite(valvepin, arduino.HIGH)
    arduino.digitalWrite(configuration.PUMP_PIN, arduino.HIGH)


def stop_pump(valve):
    valvepin = configuration.VALVE_PINS[valve]
    arduino.digitalWrite(configuration.PUMP_PIN, arduino.LOW)
    arduino.digitalWrite(valvepin, arduino.LOW)


def calculate_progress(id, progress, mixedamount, totalamount):
    current_progress = int(mixedamount / totalamount * 100)
    if current_progress != progress:
        client.call('queue.updateProgress', [id, current_progress], callback_function)

    if current_progress < 15:
        led.setColor(255, 0, 255)
    elif current_progress < 30:
        led.fadeToColor(130, 0, 255, 500)
    elif current_progress < 45:
        led.fadeToColor(0, 0, 255, 500)
    elif current_progress < 60:
        led.fadeToColor(0, 130, 255, 500)
    elif current_progress < 75:
        led.fadeToColor(0, 255, 255, 500)
    elif current_progress < 90:
        led.fadeToColor(0, 255, 130, 500)
    else:
        led.fadeToColor(0, 255, 0, 500)

    return current_progress


def check_glass(gram):
    return gram >= mixer_configuration['values']['glassweight']


def calculate_run_on_weight(mixedpartamount, mixedcocktailamount, totalcocktailamount, progress, partamount, valve,
                            queue_item):
    # measure weight richt after pump stopped
    startweight = scale.getGram()

    # cancel if glass is raised or user canceled
    if not check_glass(startweight) or queue_item['status'] == 'canceled':
        return False

    secondweight = startweight
    while True:
        firstweight = secondweight
        secondweight = scale.getGram()
        # cancel if glass was raised or user canceled
        if not check_glass(secondweight) or secondweight < startweight:
            write_log('warning', 'Glass was lifted while waiting for run on weight for valve {}'.format(valve + 1))
            return False
        if queue_item['status'] == 'canceled':
            write_log('warning',
                      'Mixing was canceled by user while waiting for run on weight for valve {}'.format(valve + 1))
            return False

        # if weight did not raise between two readings, stop waiting
        if secondweight < firstweight + 0.1:
            break

        # calculate and save progress of 100%, but only if it didn´t raise above the target weight
        mixedamount = mixedcocktailamount + mixedpartamount + (firstweight - startweight)
        if mixedamount <= mixedcocktailamount + partamount:
            progress = calculate_progress(queue_item['_id'], progress, mixedamount, totalcocktailamount)
        led.update()

    # save weight that runs on after the pump stopped for this valve
    if secondweight - startweight >= 0:
        configuration.RUN_ON_WEIGHT[valve] = secondweight - startweight
        write_log('debug',
                  'Set run-on-weight to {:.2f}g for valve {}'.format(configuration.RUN_ON_WEIGHT[valve], valve + 1))
    return True


def wait_for_ingredient_refill(queue_item, valve, ingredient):
    stop_pump(valve)
    update_status(queue_item, 'error')

    write_log('warning', 'Ingredient at valve {} empty'.format(valve + 1))

    client.call('configuration.ingredientEmpty', [valve + 1], callback_function)

    while mixer_status['value']['type'] == 'mixing':
        sleep(0.05)

    led.blink(255, 255, 0, 1000)
    while mixer_status['value']['type'] == 'ingredient_empty':
        if not check_glass(scale.getGram()):
            write_log('warning', 'Glass was lifted while refilling ingredient for valve {}'.format(valve + 1))
            return False
        if queue_item['status'] == 'canceled':
            write_log('warning',
                      'Mixing was canceled by user while refilling ingredient for valve {}'.format(valve + 1))
            return False
        led.update()
    update_status(queue_item, 'mixing')
    if ingredient['pump'] != 0:
        start_pump(valve)
    return True


def mix_recipe(recipe, queue_item):
    completed = True

    totalcocktailamount = 0
    for part in recipe:
        totalcocktailamount = totalcocktailamount + part['amount']

    progress = 0
    mixedcocktailamount = 0
    for part in recipe:
        scale_tare = scale.getGram()

        ingredient = client.find_one('ingredients', selector={'_id': part['ingredientId']})
        # valve 0 is first internally, valve 1 is first on frontend
        valve = ingredient['pump'] - 1

        write_log('debug', 'Mixing {}ml of Ingredient {}'.format(part['amount'], ingredient['name']))

        # write current part to queue
        client.call('queue.updateCurrentPart', [queue_item['_id'], part], callback_function)

        start_pump(valve)

        # subtract run on weight of last time from amount of part
        amount = part['amount'] - configuration.RUN_ON_WEIGHT[valve]
        if amount < 1:
            amount = 1
        mixedpartamount = 0
        time = datetime.now()
        while mixedpartamount < amount:
            # calculate and save progress of 100%
            progress = calculate_progress(queue_item['_id'], progress, mixedcocktailamount + mixedpartamount,
                                          totalcocktailamount)
            weight = scale.getGram()

            # if weight did not raise since configured time, ingredient is empty
            # if ingredient is empty, wait until status is reset
            if mixedpartamount + mixer_configuration['values']['checkweight'] > weight - scale_tare:
                newtime = datetime.now()
                seconds = (newtime - time).total_seconds()
                if seconds >= mixer_configuration['values']['checktime']:
                    completed = wait_for_ingredient_refill(queue_item, valve, ingredient)
                    time = datetime.now()
                    if ingredient['pump'] == 0:
                        break
            else:
                # reset time only if weight increased
                time = datetime.now()

            # cancel if glass was raised or user canceled
            if not check_glass(weight):
                write_log('warning', 'Glass was lifted while mixing cocktail')
                completed = False
            if queue_item['status'] == 'canceled':
                write_log('warning', 'Mixing was canceled by user')
                completed = False

            mixedpartamount = weight - scale_tare
            if not completed:
                break
            led.update()

        # important! always stop pump
        stop_pump(valve)

        if ingredient['pump'] == 0:
            continue

        if completed:
            # wait until liquid stops running and save the weight that ran on for next time
            if calculate_run_on_weight(mixedpartamount, mixedcocktailamount, totalcocktailamount, progress,
                                       part['amount'], valve, queue_item):
                mixedcocktailamount = mixedcocktailamount + part['amount']
            else:
                completed = False
                break
        else:
            break

    # show progress = 100%
    if completed:
        calculate_progress(queue_item['_id'], 0, totalcocktailamount, totalcocktailamount)
        write_log('debug', 'Mixing successfully completed')
    return completed


def update_status(queueItem, status):
    client.call('queue.updateStatus', [queueItem['_id'], status], callback_function)


def tare_scale():
    tareweight = scale.averageValue()
    scale.setOffset(tareweight)
    client.call('configuration.update', ["mixer", "scale_offset", tareweight], callback_function)
    return tareweight


def check_queue():
    queue_item = client.find_one('queue', selector={'status': 'start'})

    if not (queue_item is None):
        completed = True
        client.call('configuration.setStatus', ["mixing"], callback_function)

        # wait until user puts glass on scale and glass stands still
        current_weight = scale.getGram()
        if not check_glass(current_weight):
            update_status(queue_item, 'waitingforglass')
            old_weight = current_weight
            current_weight = scale.getGram()
            led.pulse(0, 0, 255, 1000)
            while (
            not check_glass(current_weight)) or current_weight > old_weight + 1 or current_weight < old_weight - 1:
                if queue_item['status'] == 'canceled':
                    write_log('warning', 'Mixing was canceled while waiting for glass')
                    completed = False
                    break
                led.update()
                old_weight = current_weight
                current_weight = scale.getGram()

        if completed:
            update_status(queue_item, 'mixing')
            led.setColor(255, 0, 255)
            cocktail = client.find_one('cocktails', selector={'_id': queue_item['cocktailId']})
            write_log('debug', 'Mixing Cocktail {}'.format(cocktail['name']))
            completed = mix_recipe(cocktail['recipe'], queue_item)

        if completed:
            update_status(queue_item, 'completed')
            client.call('history.insert', [queue_item['cocktailId'], queue_item['user']], callback_function)
            led.pulse(0, 0, 255, 1000)
        else:
            update_status(queue_item, 'canceled')
            led.blink(255, 0, 0, 1000)

        # wait until user removes glass
        while check_glass(scale.getGram()):
            sleep(0.1)
            led.update()

        led.fadeToColor(255, 0, 0, 200)
        update_status(queue_item, 'finished')
        write_log('debug', 'Finishes item ' + queue_item['_id'] + ' from queue')
        for x in range(0, 10):
            led.update()
            sleep(0.05)
        led.rainbow(20000)
        client.call('configuration.setStatus', ["idle"], callback_function)


write_log('debug', 'Cocktailmixer started')

scale.setOffset(mixer_configuration['values']['scale_offset'])
scale.setScale(mixer_configuration['values']['scale_ratio'])

client.call('configuration.setStatus', ["idle"], callback_function)

led.rainbow(20000)

# continue forever
while True:
    try:
        # find next item in queue or previously loaded
        check_queue()

        if mixer_status['value']['type'] == 'tare':
            tare_scale()
            client.call('configuration.setStatus', ["idle"], callback_function)

        if mixer_status['value']['type'] == 'start_calibrating':
            offset = tare_scale()
            while mixer_status['value']['type'] != 'calibrate':
                sleep(0.05)
            averageValue = scale.averageValue()
            ratio = (averageValue - offset) / 500
            scale.setScale(ratio)
            client.call('configuration.update', ["mixer", "scale_ratio", ratio], callback_function)
            client.call('configuration.setStatus', ["idle"], callback_function)

        if mixer_status['value']['scaleMode']:
            weight = scale.getGram()
            client.call('configuration.setCurrentWeight', [weight], callback_function)

        led.update()

    except Exception as e:
        print(e)
        write_log('error', 'Unexpected error: ' + str(e))

client.logout()
client.unsubscribe('queue')
client.unsubscribe('ingredients')
client.unsubscribe('configuration')
client.unsubscribe('cocktails')
