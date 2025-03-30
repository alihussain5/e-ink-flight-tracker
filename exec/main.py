#!/usr/bin/python
# -*- coding:utf-8 -*-
from peewee import *
from playhouse.sqlite_ext import *
from playhouse.migrate import *

from PIL import Image, ImageDraw, ImageFont
import time
from waveshare_epd import epd5in83_V2 as epd_lib
import logging
import sys
import os
import datetime
from urllib.request import urlopen
from shutil import copyfileobj

import requests
import json

picdir = os.path.join(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))), 'lib')
photosdir = os.path.join(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))), 'photos')


if os.path.exists(libdir):
    sys.path.append(libdir)


font_big = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 75)
font_big_space = 80

font_medium = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 60)
font_medium_space = 65

font_small = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 45)
font_small_space = 50

font_xs = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 30)
font_xs_space = 35 

logging.basicConfig(level=logging.DEBUG)

epd = epd_lib.EPD()
epd.reset()

db = SqliteDatabase('main.db')
migrator = SqliteMigrator(db)

# migrate(
# )


class BaseModel(Model):
    class Meta:
        database = db


class Flight(BaseModel):
    first_seen_at = DateTimeField(default=datetime.datetime.now)
    last_seen_at = DateTimeField(default=datetime.datetime.now)
    data = JSONField()
    antenna_data = JSONField()
    callsign = TextField()
    description = TextField(null = True)
    altitude = DecimalField(null = True)
    groundspeed = DecimalField(null = True)
    alt_rate = DecimalField(null = True)
    last_selected_at = DateTimeField(null=True)
    cool = BooleanField(default=False)
    photo_path = TextField(null = True)


# Flight.drop_table()
Flight.create_table()

random_flights = []


cool_planes = ['dreamliner', '747', 'a380', 'a350']
cool_routes = ['AIC176', 'SIA31', 'SIA33', 'AIC180', 'UAE226', 'QTR738']

def populate_current_flights():
    aircrafts_request = requests.get(
        'http://localhost:8080/data/aircraft.json')
    aircrafts_data = json.loads(aircrafts_request.content)
    aircrafts = aircrafts_data['aircraft']

    clean_aircrafts = [
        aircraft for aircraft in aircrafts if 'flight' in aircraft]

    for aircraft in clean_aircrafts:
        callsign = aircraft.get('flight').strip()

        existing_flight_query = Flight.select().where(Flight.callsign == callsign).limit(1)

        existing_flight = existing_flight_query[0] if len(existing_flight_query) > 0 else None

        print('New flight!: ' + callsign) if existing_flight is None else None

        # No need to repopulate if last seen within the day
        if existing_flight and datetime.datetime.now() < existing_flight.last_seen_at + datetime.timedelta(days=1):
            print('Flight ' + callsign +
                  ' already in database. Updating last seen at')
            existing_flight.update(last_seen_at=datetime.datetime.now)
            continue

        # TODO: replace with https://www.adsb.lol/docs/open-data/api/
        callsign_info = requests.get(
            'https://api.adsbdb.com/v0/callsign/' + callsign)

        if callsign_info.status_code == 200:
            flight_data = json.loads(callsign_info.content).get(
                'response').get('flightroute')

            if flight_data is None:
                continue

            cool = False

            for cool_plane in cool_planes:
                if aircraft.get('desc') and cool_plane in aircraft.get('desc').lower():
                    print('Cool plane recorded! ' + callsign)
                    cool = True

            for cool_route in cool_routes:
                if cool_route == callsign:
                    print('Cool plane recorded! ' + callsign)
                    cool = True

            local_photo = os.path.join(photosdir, callsign + '.jpg')

            photo_path = None

            if not os.path.exists(local_photo):
                photo_query = requests.get('https://api.planespotters.net/pub/photos/hex/' + aircraft.get('hex'))

                photo_data = json.loads(photo_query.content)

                if photo_data.get('photos') and len(photo_data.get('photos')) > 0:
                    thumbnail = photo_data.get('photos')[0].get(
                        'thumbnail_large').get('src')

                    with urlopen(thumbnail) as in_stream, open(local_photo, 'wb') as out_file:
                        copyfileobj(in_stream, out_file)

                    photo_path = local_photo
            else:
                photo_path = local_photo

            if existing_flight:
                existing_flight.update(
                    callsign=callsign,
                    data=flight_data,
                    antenna_data=aircraft,
                    last_seen_at=datetime.datetime.now(),
                    description = aircraft.get('desc'),
                    altitude = aircraft.get('alt_baro'),
                    groundspeed = aircraft.get('gs'),
                    alt_rate = aircraft.get('baro_rate'),
                    cool = cool,
                    photo_path = photo_path
                )
            else:
                Flight.create(
                    callsign=callsign,
                    data=flight_data,
                    antenna_data=aircraft,
                    last_seen_at=datetime.datetime.now(),
                    description = aircraft.get('desc'),
                    altitude = aircraft.get('alt_baro'),
                    groundspeed = aircraft.get('gs'),
                    alt_rate = aircraft.get('baro_rate'),
                    cool = cool,
                    photo_path = photo_path
                )

            print('logged: ', callsign)


def select_flight():
    ten_minutes_ago = datetime.datetime.now() - datetime.timedelta(minutes=60)
    one_hour_ago = datetime.datetime.now() - datetime.timedelta(hours=1)

    aircraft_query = (Flight.select()
                            .where(
                                (Flight.groundspeed.is_null(False)) & \
                                (Flight.altitude.is_null(False)) & \
                                (Flight.last_seen_at > one_hour_ago) & \
                                (Flight.photo_path.is_null(False)) & \
                                ((Flight.last_selected_at < one_hour_ago) | (Flight.last_selected_at.is_null(True)))
                            )
                            .order_by(Flight.last_selected_at.asc(), Flight.last_seen_at.desc())
                            .limit(10))

    if len(aircraft_query) == 0:
        print('No planes')
        return

    # Check for cool planes
    for aircraft in aircraft_query:
        if aircraft.cool:
            print('Cool plane found! ' + aircraft.callsign)
            return aircraft

    # Check for international
    for aircraft in aircraft_query:
        if aircraft.data.get('origin').get('country_iso_name') != 'US':
            return aircraft

        if aircraft.data.get('destination').get('country_iso_name') != 'US':
            return aircraft

    # Otherwise pick the first
    for aircraft in aircraft_query:
        if aircraft.photo_path is not None:
            return aircraft

    return aircraft_query[0]

def render_display(epd):
    epd.init()

    Limage = Image.new('1', (epd.height, epd.width), 255)  # 255: clear the frame
    draw = ImageDraw.Draw(Limage)

    aircraft_query = Flight.select().where(Flight.groundspeed.is_null(False) and Flight.altitude.is_null(False)).order_by(Flight.last_seen_at.desc()).limit(1)
    aircraft = aircraft_query[0] if len(aircraft_query) > 0 else None

    aircraft = select_flight()

    if aircraft is None:
        epd.sleep()
        return 60

    aircraft.update(last_selected_at=datetime.datetime.now())

    callsign = aircraft.callsign

    if aircraft.data.get('airline'):
        airline = aircraft.data.get('airline').get('name')
    else:
        airline = 'Unknown Airline'

    img = None

    if aircraft.photo_path:
        img = Image.open(aircraft.photo_path)

    render_wait = 5 * 60

    # If it's a cool plane, render for 30 minutes
    if aircraft.cool:
        render_wait = 30 * 60

    next_render = datetime.datetime.now() + datetime.timedelta(seconds=render_wait)
    next_render_str = next_render.strftime("%H:%M")

    origin = aircraft.data.get("origin").get('iata_code')
    origin_name = aircraft.data.get("origin").get('name')
    destination = aircraft.data.get("destination").get('iata_code')
    destination_name = aircraft.data.get("destination").get('name')
    logging.info('Displaying aircraft: ' + callsign)

    groundspeed = str(aircraft.groundspeed) + ' kt'
    altitude = str(aircraft.altitude) + ' ft'

    route = f'{origin} → {destination}'

    size = 0

    draw.text((35, size), callsign, font=font_medium, fill=0)
    draw.text((300, size), 'Next: ' + next_render_str, font=font_xs, fill=0)
    if aircraft.cool:
        draw.text((370, size + font_xs_space), '😮', font=font_xs, fill=0)
    size += font_medium_space

    draw.text((35, size), route, font=font_big, fill=0)
    size += font_big_space
    if aircraft.description is not None:
        draw.text((35, size), aircraft.description, font=font_xs, fill=0)
    size += font_small_space + 5 

    draw.text((35, size), 'Speed', font=font_small, fill=0)
    draw.text((250, size), groundspeed, font=font_small, fill=0)
    size += font_small_space

    draw.text((35, size), 'Alt', font=font_small, fill=0)
    draw.text((250, size), altitude, font=font_small, fill=0)
    size += font_small_space

    if aircraft.alt_rate is None or aircraft.alt_rate == 0:
        draw.text((35, size), 'Cruising', font=font_xs, fill=0)
    elif aircraft.alt_rate < 0:
        draw.text((35, size), '↓ ' + str(aircraft.alt_rate * -1) + ' ft/min', font=font_xs, fill=0)
        # rate = str(aircraft.alt_rate * -1) + ' ft/min'
        # draw.text((200, size), rate, font=font_xs, fill=0)
    else:
        draw.text((35, size), '↑ ' + str(aircraft.alt_rate) + ' ft/min', font=font_xs, fill=0)
        # draw.text((35, size), '↑', font=font_xs, fill=0)
        # rate = str(aircraft.alt_rate) + ' ft/min'
        # draw.text((200, size), rate, font=font_xs, fill=0)

    size += font_small_space + 20


    # draw.text((2, size), airline, font=font_small, fill=0)
    # size += font_small_space

    if img:
        img_w, img_h = img.size
        bg_w, bg_h = Limage.size

        print('img_w: ' + str(img_w))
        print('img_h: ' + str(img_h))
        Limage.paste(img, (((bg_w - img_w) // 2) - 10, bg_h - img_h))

    epd.display(epd.getbuffer(Limage))
    epd.sleep()

    return render_wait

start = None
render_wait = 5 * 60

while 1:
    now = time.time()

    try:
        populate_current_flights()

        if start is None or now - start >= render_wait:
            start = now
            render_wait = render_display(epd)
        else:
            print(str(render_wait - (now - start)) + ' seconds until next render')

        time.sleep(5)

    except IOError as e:
        logging.info(e)

    except KeyboardInterrupt:
        logging.info("ctrl + c:")
        epd.Clear()
        epd_lib.epdconfig.module_exit(cleanup=True)
        exit()

epd.Clear()
epd_lib.epdconfig.module_exit(cleanup=True)
