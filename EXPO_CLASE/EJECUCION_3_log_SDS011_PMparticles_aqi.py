#!/usr/bin/python -u
# coding=utf-8

#ProyectoSEI
#German Artigot Cortizo && Segundo Moreno Torres

#1º Máster Ingeniería de Telecomunicación


from __future__ import print_function
import serial, struct, sys, time, json, subprocess
#Para el sensor de temperatura y humedad
import Adafruit_DHT
#Para el sensor de presión
from BMP180 import BMP180
import MCP3008
from mq import *




#def write_log(text):
#    log=open(log_path+time.strftime("%d.%m.%Y %H:%M")+"_dht.log","a")
#line=time.strftime("%d.%m.%Y %H:%M:%S")+" "+text+"\n"
#log.write(line)
 #   log.close()

DEBUG = 0
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1
PERIOD_CONTINUOUS = 0

JSON_FILE = '/var/www/html/aqi.json'
##CREACION ARCHIVO LOG
log_path="/var/log/iot/"
LOG_FILE = '/var/log/iot/log.txt'


MQTT_HOST = ''
MQTT_TOPIC = '/weather/particulatematter'

ser = serial.Serial()
ser.port = "/dev/ttyUSB0"
ser.baudrate = 9600

ser.open()
ser.flushInput()

byte, data = 0, ""

print ("\n   AQI Values   ||     Level of Health     \n")
print ("\n     0 - 50     ||           Good          ")
print ("\n    51 - 100    ||          Normal         ")
print ("\n    101 -150    ||Unhealthy for some groups")
print ("\n    151 -200    ||         Unhealthy       ")
print ("\n    201 -300    ||      Very unhealthy     ")
print ("\n    301 -500    ||         Hazardous       \n\n")

#Parte del sensor de temperatura
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 21
humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
print ("\nSensor SDS011_DHT22: TEMP={0:0.1f}*C Humidity={1:0.1f}%".format(temperature, humidity))

#Parte del sensor de presión
# Initialise the BMP085 and use STANDARD mode (default value)
# bmp = BMP085(0x77, debug=True)
bmp = BMP180()
temp = bmp.read_temperature()
pressure = bmp.read_pressure()
altitude = bmp.read_altitude()
print("\nBMP180 sensor values:")
print ("Temperature: " , temp, "ºC")
print ("Pressure: " , (pressure / 100.0), "hPa")
print ("Altitude: " , altitude, "m\n")


#Parte del sensor de CO y ppm (MQ135)
mq = MQ();
perc = mq.MQPercentage()
print ("\nSensor MQ-135\n")
sys.stdout.write("\r")
sys.stdout.write("\033[K")
sys.stdout.write("LPG: %g ppm, CO: %g ppm, Smoke: %g ppm" % (perc["GAS_LPG"], perc["CO"], perc["SMOKE"]))



def dump(d, prefix=''):
    print(prefix + ' '.join(x.encode('hex') for x in d))

def construct_command(cmd, data=[]):
    assert len(data) <= 12
    data += [0,]*(12-len(data))
    checksum = (sum(data)+cmd-2)%256
    ret = "\xaa\xb4" + chr(cmd)
    ret += ''.join(chr(x) for x in data)
    ret += "\xff\xff" + chr(checksum) + "\xab"

    if DEBUG:
        dump(ret, '> ')
    return ret

def process_data(d):
    r = struct.unpack('<HHxxBB', d[2:])
    pm25 = r[0]/10.0
    pm10 = r[1]/10.0
    checksum = sum(ord(v) for v in d[2:8])%256
    return [pm25, pm10]
    #print("PM 2.5: {} μg/m^3  PM 10: {} μg/m^3 CRC={}".format(pm25, pm10, "OK" if (checksum==r[2] and r[3]==0xab) else "NOK"))

def process_version(d):
    r = struct.unpack('<BBBHBB', d[3:])
    checksum = sum(ord(v) for v in d[2:8])%256
    print("Y: {}, M: {}, D: {}, ID: {}, CRC={}".format(r[0], r[1], r[2], hex(r[3]), "OK" if (checksum==r[4] and r[5]==0xab) else "NOK"))

def read_response():
    byte = 0
    while byte != "\xaa":
        byte = ser.read(size=1)

    d = ser.read(size=9)

    if DEBUG:
        dump(d, '< ')
    return byte + d

def cmd_set_mode(mode=MODE_QUERY):
    ser.write(construct_command(CMD_MODE, [0x1, mode]))
    read_response()

def cmd_query_data():
    ser.write(construct_command(CMD_QUERY_DATA))
    d = read_response()
    values = []
    if d[1] == "\xc0":
        values = process_data(d)
    return values

def cmd_set_sleep(sleep):
    mode = 0 if sleep else 1
    ser.write(construct_command(CMD_SLEEP, [0x1, mode]))
    read_response()

def cmd_set_working_period(period):
    ser.write(construct_command(CMD_WORKING_PERIOD, [0x1, period]))
    read_response()

def cmd_firmware_ver():
    ser.write(construct_command(CMD_FIRMWARE))
    d = read_response()
    process_version(d)

def cmd_set_id(id):
    id_h = (id>>8) % 256
    id_l = id % 256
    ser.write(construct_command(CMD_DEVICE_ID, [0]*10+[id_l, id_h]))
    read_response()

def pub_mqtt(jsonrow):
    cmd = ['mosquitto_pub', '-h', MQTT_HOST, '-t', MQTT_TOPIC, '-s']
    print('Publishing using:', cmd)
    with subprocess.Popen(cmd, shell=False, bufsize=0, stdin=subprocess.PIPE).stdin as f:
        json.dump(jsonrow, f)


if __name__ == "__main__":
    cmd_set_sleep(0)
    cmd_firmware_ver()
    cmd_set_working_period(PERIOD_CONTINUOUS)
    cmd_set_mode(MODE_QUERY);
    while True:
        cmd_set_sleep(0)
        for t in range(15):
            values = cmd_query_data();
            humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
            temp = bmp.read_temperature()
            pressure = bmp.read_pressure()
            altitude = bmp.read_altitude()
            perc = mq.MQPercentage()
            LPG = perc["GAS_LPG"]
            CO = perc["CO"]
            Smoke = perc["SMOKE"]
            
            #Valores que muestra en terminal
            if values is not None and len(values) == 2:           
              print("\nPM2.5: ", values[0], ", PM10: ", values[1])
              print("\nTEMP DHT22:",temperature,"ºC","HUM DHT22:",humidity,"%",
                    "PRESS BMP180",pressure,"Pa","...",altitude,"m","TempBMP180",temp)
              print ("\nLPG",LPG,"CO",CO,"SMOKE",Smoke)


              time.sleep(2)

        # open stored data
        try:
            with open(JSON_FILE) as json_data:
                data = json.load(json_data)
        except IOError as e:
            data = []

        # check if length is more than 100 and delete first element
        if len(data) > 100:
            data.pop(0)


        #Cargar datos el log (anteriores)
        log=open("/var/log/iot/log.txt","a") #cambiar a log.txt
        log_data=[]
        log_data=log
        logrow=[]
        logrow = [values[0],values[1],temperature,
                   humidity,LPG,CO,Smoke,
                   time.strftime("%d.%m.%Y %H:%M:%S")]
        
        logrow_str=','.join(str(elem) for elem in logrow)
        print(logrow_str)
        log_data.write(logrow_str)
        log_data.write("\n")
        log.close()
        
        
        #Leer ultimos 15 valores de temp y hum para graficas
        log=open("/var/log/iot/log_1h.txt","r")
        lines=log.readlines()
        last_lines=lines[-15:]
        temp_=[]
        hum_=[]
        for i in last_lines:
            lists_str=i.split(',')
            temp_.append(lists_str[2])
            hum_.append(lists_str[3])
        

        # append new values
        jsonrow = {'pm25': values[0], 'pm10': values[1], 'temp': temperature,
                   'hum':humidity,'LPG':LPG,'CO':CO,'Smoke':Smoke,
                   'time': time.strftime("%d.%m.%Y %H:%M:%S"),
                   'temp0': temp_[0],'temp1': temp_[1],'temp2': temp_[2],
                   'temp3': temp_[3],'temp4': temp_[4],'temp5': temp_[5],
                   'temp6': temp_[6],'temp7': temp_[7],'temp8': temp_[8],
                   'temp9': temp_[9],'hum0': hum_[0],'hum1': hum_[1],
                   'hum2': hum_[2],'hum3': hum_[3],'hum4': hum_[4],
                   'hum5': hum_[5],'hum6': hum_[6],'hum7': hum_[7],
                   'hum8': hum_[8],'hum9': hum_[9]}
        data.append(jsonrow)
        log.close()
        with open(JSON_FILE, 'w') as outfile:
            json.dump(data, outfile, sort_keys=True)
            #json.dump(data, outfile, sort_keys=True)


        if MQTT_HOST != '':
            pub_mqtt(jsonrow)
         

        print("\nGoing to sleep for 1 min...") #1 min
        print("\nPress Ctrl^C to STOP")
        cmd_set_sleep(1)
        time.sleep(60)        #60 originalmente
