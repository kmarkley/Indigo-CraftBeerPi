#! /usr/bin/env python
# -*- coding: utf-8 -*-
###############################################################################
# http://www.indigodomo.com

import indigo
import time
import re
import socket
from urlparse import urlparse
import requests

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

###############################################################################
# globals

k_stateImages = {
    'cooling' : indigo.kStateImageSel.HvacCooling,
    'heating' : indigo.kStateImageSel.HvacHeating,
    'active'  : indigo.kStateImageSel.TemperatureSensorOn,
    'passive' : indigo.kStateImageSel.TemperatureSensor,
    'running' : indigo.kStateImageSel.PowerOn,
    'stopped' : indigo.kStateImageSel.PowerOff,
    'online'  : indigo.kStateImageSel.SensorOn,
    'offline' : indigo.kStateImageSel.AvStopped,
    }

################################################################################
class Plugin(indigo.PluginBase):
    #-------------------------------------------------------------------------------
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

    def __del__(self):
        indigo.PluginBase.__del__(self)

    #-------------------------------------------------------------------------------
    # Start, Stop and Config changes
    #-------------------------------------------------------------------------------
    def startup(self):
        self.debug = self.pluginPrefs.get("showDebugInfo",False)
        self.logger.debug("startup")
        if self.debug:
            self.logger.debug("Debug logging enabled")
        self.serverDict = dict()
        self.objectDict = dict()

    #-------------------------------------------------------------------------------
    def shutdown(self):
        self.logger.debug("shutdown")
        self.pluginPrefs["showDebugInfo"] = self.debug

    #-------------------------------------------------------------------------------
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.logger.debug("closedPrefsConfigUi")
        if not userCancelled:
            self.debug = valuesDict.get("showDebugInfo",False)
            if self.debug:
                self.logger.debug("Debug logging enabled")

    #-------------------------------------------------------------------------------
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug("validatePrefsConfigUi")
        errorsDict = indigo.Dict()

        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    def runConcurrentThread(self):
        try:
            while True:
                for cbpi_server_device in self.serverDict.values():
                    cbpi_server_device.update()
                self.sleep(1)
        except self.StopThread:
            pass    # Optionally catch the StopThread exception and do any needed cleanup.
    #-------------------------------------------------------------------------------
    # Device Methods
    #-------------------------------------------------------------------------------
    def deviceStartComm(self, dev):
        self.logger.debug("deviceStartComm: {}".format(dev.name))
        if dev.version != self.pluginVersion:
            self.updateDeviceVersion(dev)

        if dev.deviceTypeId == 'cbpi-server':
            self.serverDict[dev.id] = CBPiServer(dev, self.objectDict, self.logger)
        elif dev.deviceTypeId == 'cbpi-kettle':
            self.objectDict[dev.id] = CBPiKettle(dev, self.serverDict, self.logger)
        elif dev.deviceTypeId == 'cbpi-fermenter':
            self.objectDict[dev.id] = CBPiFermenter(dev, self.serverDict, self.logger)
        elif dev.deviceTypeId == 'cbpi-actor':
            self.objectDict[dev.id] = CBPiActor(dev, self.serverDict, self.logger)
        elif dev.deviceTypeId == 'cbpi-sensor':
            self.objectDict[dev.id] = CBPiSensor(dev, self.serverDict, self.logger)

    #-------------------------------------------------------------------------------
    def deviceStopComm(self, dev):
        self.logger.debug("deviceStopComm: {}".format(dev.name))
        if dev.id in self.serverDict:
            del self.serverDict[dev.id]
        if dev.id in self.objectDict:
            del self.objectDict[dev.id]

    #-------------------------------------------------------------------------------
    def validateDeviceConfigUi(self, valuesDict, typeId, devId, runtime=False):
        self.logger.debug("validateDeviceConfigUi: " + typeId)
        errorsDict = indigo.Dict()

        if typeId == 'cbpi-server':
            address = valuesDict.get('cbpi_address','')
            port = valuesDict.get('cbpi_port','')
            url = u'http://{}:{}'.format(address,port)
            if not any([is_valid_hostname(address),is_valid_ipv4_address(address),is_valid_ipv6_address(address)]):
                errorsDict['cbpi_address'] = "Not valid IP or host name"
            if not validateTextFieldNumber(port, numberType=int, zeroAllowed=False, negativeAllowed=False, maximumAllowed=65535):
                errorsDict['cdpi_port'] = "Invalid port number"
            if is_valid_url(url):
                valuesDict['address'] = url
        else:
            server_id = int(valuesDict.get('server_id',0))
            cbpi_id = int(valuesDict.get('cbpi_id',0))
            if not server_id:
                errorsDict['server_id'] = 'Required'
            elif not cbpi_id:
                errorsDict['cbpi_id'] = 'Required'
            else:
                server_device = self.serverDict.get(server_id)
                address = server_device.device.pluginProps.get('address')
                valuesDict['address'] = address

        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    def updateDeviceVersion(self, dev):
        theProps = dev.pluginProps
        # update states
        dev.stateListOrDisplayStateIdChanged()
        # check for props

        # push to server
        theProps["version"] = self.pluginVersion
        dev.replacePluginPropsOnServer(theProps)

    #-------------------------------------------------------------------------------
    # Action Methods
    #-------------------------------------------------------------------------------
    def actionControlSensor(self, action, device):
        if action.sensorAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info('"{}" status update'.format(device.name))
            cbpi_device_id = device.id
            if self.objectDict.get(cbpi_device_id):
                cbpi_device_id = self.objectDict.get(cbpi_device_id).server_id
            self.serverDict.get(cbpi_device_id).update(True)
        else:
            self.logger.debug('"{}" {} request ignored'.format(dev.name, unicode(action.speedControlAction)))

    #-------------------------------------------------------------------------------
    # Menu Methods
    #-------------------------------------------------------------------------------
    def toggleDebug(self):
        if self.debug:
            self.logger.debug("Debug logging disabled")
            self.debug = False
        else:
            self.debug = True
            self.logger.debug("Debug logging enabled")

    #-------------------------------------------------------------------------------
    # Menu Callbacks
    #-------------------------------------------------------------------------------
    def dummyCallback(self, valuesDict, typeId, devId):
        pass

    #-------------------------------------------------------------------------------
    def cbpiOblectList(self, filter="", valuesDict=None, typeId="", targetId=0):
        server_id = int(valuesDict.get('server_id',0))
        if server_id:
            server_data = self.serverDict.get(server_id).getData()
            if server_data:
                obj_data = server_data.get(filter)
                return [(obj['id'],obj['name']) for obj in obj_data.values()]
        return [(0,'(select server first)')]

################################################################################
# Classes
################################################################################
class CBPiBaseClass(object):
    #-------------------------------------------------------------------------------
    def __init__(self, device, logger):
        self.logger = logger
        self.device = device
        self.stateList = list()

    #-------------------------------------------------------------------------------
    def addToStateList(self, key, value, uiValue=None, decimals=None):
        if self.device.states[key] != value:
            self.stateList.append({
                'key'      : key,
                'value'    : value,
                'uiValue'  : uiValue,
                'decimals' : decimals,
                })

    #-------------------------------------------------------------------------------
    def updateIndigoDeviceStates(self):
        if self.stateList:
            self.device.updateStatesOnServer(self.stateList)
            for state in self.stateList:
                if state['key'] == 'status':
                    self.device.updateStateImageOnServer(k_stateImages[state['value']])
                    break
            self.stateList = list()

    #-------------------------------------------------------------------------------
    @property
    def name(self):
        return self.device.name

################################################################################
class CBPiServer(CBPiBaseClass):
    #-------------------------------------------------------------------------------
    def __init__(self, device, objectDict, logger):
        super(CBPiServer, self).__init__(device, logger)
        self.objectDict = objectDict

        self.update_frequency = float(device.pluginProps.get('update_frequency', 0))

        server = device.pluginProps.get('cbpi_address')
        port = device.pluginProps.get('cbpi_port')
        self.cbpi_url = 'http://{}:{}'.format(server,port)

        self.last_refresh = 0
        self.__refresh = True
        self.__data = dict()

    #-------------------------------------------------------------------------------
    def getData(self, force=False):
        if force:
            self.last_refresh = time.time()
            try:
                r = requests.get(self.cbpi_url)
                r.raise_for_status()
                self.__data = r.json()
            except Exception as e:
                self.logger.debug('requests exception: {}'.format(e))
                self.__data = dict()
        return self.__data

    #-------------------------------------------------------------------------------
    def update(self, force=False):
        if force or (time.time() >= self.last_refresh + self.update_frequency):
            server = self.getData(True)
            if server:
                self.addToStateList('status', 'online')
                self.addToStateList('onOffState', True)
                self.addToStateList('brewery', server['config']['brewery'])
                self.addToStateList('brew_name', server['config']['brew_name'])

                if server.get('messages'):
                    message = server['messages'][-1]
                    self.addToStateList('message', '{} | {}'.format(message['headline'],message['message']))
                else:
                    self.addToStateList('message', u'')

                for step in server['steps']:
                    if step['state'] == u'A':
                        self.addToStateList('step_name', step['name'])
                        self.addToStateList('step_number', step['order'])
                        break
                else:
                    self.addToStateList('step_name', u'')
                    self.addToStateList('step_number', 0)

            else:
                self.addToStateList('status', 'offline')
                self.addToStateList('onOffState', False)

            self.updateIndigoDeviceStates()

            for obj in self.objectDict.values():
                if obj.server_id == self.device.id:
                    obj.update()

################################################################################
class CBPiObject(CBPiBaseClass):
    #-------------------------------------------------------------------------------
    def __init__(self, device, serverDict, logger):
        super(CBPiObject, self).__init__(device, logger)
        self.serverDict = serverDict
        self.server_id = int(self.device.pluginProps.get('server_id',0))
        self.cbpi_id   = self.device.pluginProps.get('cbpi_id')

    #-------------------------------------------------------------------------------
    def getData(self):
        try:
            server_data = self.serverDict.get(self.server_id).getData()
            object_data = server_data.get(self.cbpi_type).get(self.cbpi_id)
            return object_data
        except:
            return {}

    #-------------------------------------------------------------------------------
    def getObjectData(self, object_type, object_id):
        try:
            server_data = self.serverDict.get(self.server_id).getData()
            obj_data = server_data.get(object_type).get(str(object_id))
            return obj_data
        except:
            return {}

################################################################################
class CBPiKettle(CBPiObject):
    #-------------------------------------------------------------------------------
    def __init__(self, device, serverDict, logger):
        self.cbpi_type = 'kettles'
        super(CBPiKettle, self).__init__(device, serverDict, logger)

    #-------------------------------------------------------------------------------
    def update(self):
        kettle = self.getData()

        if kettle:
            self.addToStateList('name',       kettle['name'])
            self.addToStateList('logic',      kettle['logic'])
            self.addToStateList('target',     kettle['target'], uiValue=u'{}{}'.format(round(kettle['target'],1),kettle['unit']), decimals=1)
            self.addToStateList('auto',       kettle['state'])
            self.addToStateList('onOffState', kettle['state'])

            sensor   = self.getObjectData('sensors', kettle['sensor'])
            heater   = self.getObjectData('actors',  kettle['heater'])
            agitator = self.getObjectData('actors',  kettle['agitator'])

            if sensor:
                self.addToStateList('sensor_name',  sensor['name'])
                self.addToStateList('sensor_value', round(sensor['value'],6), uiValue=u'{}{}'.format(round(sensor['value'],3),sensor['unit']), decimals=3)
                self.addToStateList('sensorValue',  round(sensor['value'],6), uiValue=u'{}{}'.format(round(sensor['value'],3),sensor['unit']), decimals=3)
            if heater:
                self.addToStateList('heater_name',  heater['name'])
                self.addToStateList('heater_state', heater['state'])
                self.addToStateList('heater_power', heater['power'], uiValue=u'{}%'.format(heater['power']))
            if agitator:
                self.addToStateList('agitator_name',  agitator['name'])
                self.addToStateList('agitator_state', agitator['state'])
                self.addToStateList('agitator_power', agitator['power'], uiValue=u'{}%'.format(agitator['power']))


            # status
            if heater and heater['state']:
                self.addToStateList('status', 'heating')
            elif kettle['state']:
                self.addToStateList('status', 'active')
            else:
                self.addToStateList('status', 'passive')
        else:
            self.addToStateList('status', 'offline')

        self.updateIndigoDeviceStates()

################################################################################
class CBPiFermenter(CBPiObject):
    #-------------------------------------------------------------------------------
    def __init__(self, device, serverDict, logger):
        self.cbpi_type = 'fermenters'
        super(CBPiFermenter, self).__init__(device, serverDict, logger)

    #-------------------------------------------------------------------------------
    def update(self):
        fermenter = self.getData()

        if fermenter:
            self.addToStateList('name',       fermenter['name'])
            self.addToStateList('logic',      fermenter['logic'])
            self.addToStateList('brew',       fermenter['brew'])
            self.addToStateList('target',     fermenter['target'], uiValue=u'{}{}'.format(round(fermenter['target'],1),fermenter['unit']), decimals=1)
            self.addToStateList('auto',       fermenter['state'])
            self.addToStateList('onOffState', fermenter['state'])

            sensor1 = self.getObjectData('sensors', fermenter['sensor1'])
            sensor2 = self.getObjectData('sensors', fermenter['sensor2'])
            sensor3 = self.getObjectData('sensors', fermenter['sensor3'])
            heater  = self.getObjectData('actors',  fermenter['heater'])
            cooler  = self.getObjectData('actors',  fermenter['cooler'])

            if sensor1:
                self.addToStateList('sensor1_name',  sensor1['name'])
                self.addToStateList('sensor1_value', round(sensor1['value'],6), uiValue=u'{}{}'.format(round(sensor1['value'],3),sensor1['unit']), decimals=3)
                self.addToStateList('sensorValue',   round(sensor1['value'],6), uiValue=u'{}{}'.format(round(sensor1['value'],3),sensor1['unit']), decimals=3)
            if sensor2:
                self.addToStateList('sensor2_name',  sensor2['name'])
                self.addToStateList('sensor2_value', round(sensor2['value'],6), uiValue=u'{}{}'.format(round(sensor2['value'],3),sensor2['unit']), decimals=3)
            if sensor3:
                self.addToStateList('sensor3_name',  sensor3['name'])
                self.addToStateList('sensor3_value', round(sensor3['value'],6), uiValue=u'{}{}'.format(round(sensor3['value'],3),sensor3['unit']), decimals=3)
            if heater:
                self.addToStateList('heater_name',  heater['name'])
                self.addToStateList('heater_state', heater['state'])
                self.addToStateList('heater_power', heater['power'], uiValue=u'{}%'.format(heater['power']))
            if cooler:
                self.addToStateList('cooler_name',  cooler['name'])
                self.addToStateList('cooler_state', cooler['state'])
                self.addToStateList('cooler_power', cooler['power'], uiValue=u'{}%'.format(cooler['power']))

            for step in fermenter['steps']:
                if step['state'] == u'A':
                    self.addToStateList('step_name',   step['name'])
                    self.addToStateList('step_number', step['order'])
                    break
            else:
                self.addToStateList('step_name', u'')
                self.addToStateList('step_number', 0)

            # status
            if cooler and cooler['state']:
                self.addToStateList('status', 'cooling')
            elif heater and heater['state']:
                self.addToStateList('status', 'heating')
            elif fermenter['state']:
                self.addToStateList('status', 'active')
            else:
                self.addToStateList('status', 'passive')
        else:
            self.addToStateList('status', 'offline')

        self.updateIndigoDeviceStates()

################################################################################
class CBPiActor(CBPiObject):
    #-------------------------------------------------------------------------------
    def __init__(self, device, serverDict, logger):
        self.cbpi_type = 'actors'
        super(CBPiActor, self).__init__(device, serverDict, logger)

    #-------------------------------------------------------------------------------
    def update(self):
        actor = self.getData()
        if actor:
            self.addToStateList('status', ['stopped','running'][actor['state']])
            self.addToStateList('name', actor['name'])
            self.addToStateList('onOffState', actor['state'])
            self.addToStateList('type', actor['type'])
            self.addToStateList('power', actor['power'], uiValue=u'{}%'.format(actor['power']))
        else:
            self.addToStateList('status', 'offline')

        self.updateIndigoDeviceStates()

################################################################################
class CBPiSensor(CBPiObject):
    #-------------------------------------------------------------------------------
    def __init__(self, device, serverDict, logger):
        self.cbpi_type = 'sensors'
        super(CBPiSensor, self).__init__(device, serverDict, logger)

    #-------------------------------------------------------------------------------
    def update(self):
        sensor = self.getData()
        if sensor:
            self.addToStateList('name', sensor['name'])
            self.addToStateList('type', sensor['type'])
            self.addToStateList('sensorValue', round(sensor['value'],6), uiValue=u'{}{}'.format(round(sensor['value'],3),sensor['unit']), decimals=3)
            self.addToStateList('status', 'online')
        else:
            self.addToStateList('status', 'offline')
        self.updateIndigoDeviceStates()

################################################################################
# Utilities
################################################################################
def validateTextFieldNumber(rawInput, numberType=float, zeroAllowed=True, negativeAllowed=True, minimumAllowed=None, maximumAllowed=None):
    try:
        num = numberType(rawInput)
        if not zeroAllowed:
            if num == 0: raise
        if not negativeAllowed:
            if num < 0: raise
        if minimumAllowed is not None:
            if num < minimumAllowed: raise
        if maximumAllowed is not None:
            if num > maximumAllowed: raise
        return True
    except:
        return False

#-------------------------------------------------------------------------------
# http://stackoverflow.com/questions/2532053/validate-a-hostname-string
def is_valid_hostname(hostname):
    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]
    if len(hostname) > 253:
        return False
    labels = hostname.split(".")
    # the TLD must be not all-numeric
    if re.match(r"[0-9]+$", labels[-1]):
        return False
    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(label) for label in labels)

#-------------------------------------------------------------------------------
# http://stackoverflow.com/questions/319279/how-to-validate-ip-address-in-python
def is_valid_ipv4_address(address):
    try:
        socket.inet_pton(socket.AF_INET, address)
    except AttributeError:  # no inet_pton here, sorry
        try:
            socket.inet_aton(address)
        except socket.error:
            return False
        return address.count('.') == 3
    except socket.error:  # not a valid address
        return False
    return True
def is_valid_ipv6_address(address):
    try:
        socket.inet_pton(socket.AF_INET6, address)
    except socket.error:  # not a valid address
        return False
    return True

#-------------------------------------------------------------------------------
# http://stackoverflow.com/questions/7160737/python-how-to-validate-a-url-in-python-malformed-or-not#7160819
def is_valid_url(url, qualifying=None):
    min_attributes = ('scheme', 'netloc')
    qualifying = min_attributes if qualifying is None else qualifying
    token = urlparse(url)
    return all([getattr(token, qualifying_attr) for qualifying_attr in qualifying])

#-------------------------------------------------------------------------------
def ver(vstr): return tuple(map(int, (vstr.split('.'))))
