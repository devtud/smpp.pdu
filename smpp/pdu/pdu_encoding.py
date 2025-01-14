import binascii
import io
import struct
from typing import Any

from smpp.pdu import constants, pdu_types, operations
from smpp.pdu import smpp_time
from smpp.pdu.error import PDUParseError, PDUCorruptError


class IEncoder(object):

    def encode(self, value: Any) -> bytes:
        """Takes an object representing the type and returns a byte string"""
        raise NotImplementedError()

    def decode(self, file: io.BytesIO):
        """Takes file stream in and returns an object representing the type"""
        raise NotImplementedError()

    def read(self, file: io.BytesIO, size: int) -> bytes:
        bytes_read = file.read(size)
        length = len(bytes_read)
        if length == 0:
            raise PDUCorruptError("Unexpected EOF",
                                  pdu_types.CommandStatus.ESME_RINVMSGLEN)
        if length != size:
            raise PDUCorruptError(
                "Length mismatch. Expecting %d bytes. Read %d" % (size, length),
                pdu_types.CommandStatus.ESME_RINVMSGLEN)
        return bytes_read


class EmptyEncoder(IEncoder):

    def encode(self, value) -> bytes:
        return b''

    def decode(self, file: io.BytesIO):
        return None


class PDUNullableFieldEncoder(IEncoder):
    nullHex = None
    nullable = True
    decodeNull = False
    requireNull = False

    def __init__(self, **kwargs):
        self.nullable = kwargs.get('nullable', self.nullable)
        self.decodeNull = kwargs.get('decodeNull', self.decodeNull)
        self.requireNull = kwargs.get('requireNull', self.requireNull)
        self._validateParams()

    def _validateParams(self):
        if self.decodeNull:
            if not self.nullable:
                raise ValueError("nullable must be set if decodeNull is set")
        if self.requireNull:
            if not self.decodeNull:
                raise ValueError("decodeNull must be set if requireNull is set")

    def encode(self, value) -> bytes:
        if value is None:
            if not self.nullable:
                raise ValueError("Field is not nullable")
            if self.nullHex is None:
                raise NotImplementedError("No value for null")
            return binascii.a2b_hex(self.nullHex)
        if self.requireNull:
            raise ValueError(f'Field must be null ({self.requireNull})')
        return self._encode(value)

    def decode(self, file: io.BytesIO):
        bytes_ = self._read(file)
        if self.decodeNull:
            if self.nullHex is None:
                raise NotImplementedError("No value for null")
            if self.nullHex == binascii.b2a_hex(bytes_):
                return None
            if self.requireNull:
                raise PDUParseError(f"Field must be null ({self.requireNull})",
                                    pdu_types.CommandStatus.ESME_RUNKNOWNERR)
        return self._decode(bytes_)

    def _encode(self, value):
        """Takes an object representing the type and returns a byte string"""
        raise NotImplementedError()

    def _read(self, file):
        """Takes file stream in and returns raw bytes"""
        raise NotImplementedError()

    def _decode(self, bytes_):
        """Takes bytes in and returns an object representing the type"""
        raise NotImplementedError()


# pylint: disable-msg=E0213
def assertFmtSizes(sizeFmtMap):
    for (size, fmt) in list(sizeFmtMap.items()):
        assert struct.calcsize(fmt) == size


class IntegerBaseEncoder(PDUNullableFieldEncoder):
    size = None
    sizeFmtMap = {
        1: '!B',
        2: '!H',
        4: '!L',
    }

    # Verify platform sizes match protocol
    assertFmtSizes(sizeFmtMap)

    def __init__(self, **kwargs):
        PDUNullableFieldEncoder.__init__(self, **kwargs)

        self.nullHex = b'00' * self.size

        self.max = 2 ** (8 * self.size) - 1
        self.min = 0
        if 'max' in kwargs:
            if kwargs['max'] > self.max:
                raise ValueError("Illegal value for max %d" % kwargs['max'])
            self.max = kwargs['max']
        if 'min' in kwargs:
            if kwargs['min'] < self.min:
                raise ValueError("Illegal value for min %d" % kwargs['min'])
            self.min = kwargs['min']
        if self.nullable and self.min > 0:
            self.decodeNull = True

    def _encode(self, value):
        if value > self.max:
            raise ValueError("Value %d exceeds max %d" % (value, self.max))
        if value < self.min:
            raise ValueError("Value %d is less than min %d" % (value, self.min))
        return struct.pack(self.sizeFmtMap[self.size], value)

    def _read(self, file: io.BytesIO) -> bytes:
        return self.read(file, self.size)

    def _decode(self, bytes_: bytes):
        return struct.unpack(self.sizeFmtMap[self.size], bytes_)[0]


class Int4Encoder(IntegerBaseEncoder):
    size = 4


class Int1Encoder(IntegerBaseEncoder):
    size = 1


class Int2Encoder(IntegerBaseEncoder):
    size = 2


class OctetStringEncoder(PDUNullableFieldEncoder):
    nullable = False

    def __init__(self, size=None, **kwargs):
        PDUNullableFieldEncoder.__init__(self, **kwargs)
        self.size = size

    def getSize(self):
        if callable(self.size):
            return self.size()
        return self.size

    def _encode(self, value) -> bytes:
        length = len(value)
        if self.getSize() is not None:
            if length != self.getSize():
                raise ValueError(
                    "Value size %d does not match expected %d" % (length, self.getSize()))
        return value

    def _read(self, file: io.BytesIO) -> bytes:
        if self.getSize() is None:
            raise AssertionError("Missing size to decode")
        if self.getSize() == 0:
            return b''
        return self.read(file, self.getSize())

    def _decode(self, bytes_: bytes):
        return bytes_


class COctetStringEncoder(PDUNullableFieldEncoder):
    nullHex = b'00'
    decodeErrorClass = PDUParseError
    decode_error_status = pdu_types.CommandStatus.ESME_RUNKNOWNERR

    def __init__(self, maxSize=None, **kwargs):
        PDUNullableFieldEncoder.__init__(self, **kwargs)
        if maxSize is not None and maxSize < 1:
            raise ValueError("maxSize must be > 0")
        self.maxSize = maxSize
        self.decodeErrorClass = kwargs.get('decodeErrorClass', self.decodeErrorClass)
        self.decode_error_status = kwargs.get('decode_error_status', self.decode_error_status)

    def _encode(self, value: str) -> bytes:
        asciiVal = value.encode('ascii')
        length = len(asciiVal)
        if self.maxSize is not None:
            if length + 1 > self.maxSize:
                raise ValueError(
                    "COctetString is longer than allowed maximum size (%d): %s" % (
                        self.maxSize, asciiVal)
                )
        encoded = struct.pack("%ds" % length, asciiVal) + b'\0'
        assert len(encoded) == length + 1
        return encoded

    def _read(self, file: io.BytesIO) -> bytes:
        result = b''
        while True:
            c = self.read(file, 1)
            result += c
            if c == b'\0':
                break
        return result

    def _decode(self, bytes_: bytes) -> str:
        if self.maxSize is not None:
            if len(bytes_) > self.maxSize:
                errStr = "COctetString is longer than allowed maximum size (%d)" % (
                    self.maxSize)
                raise self.decodeErrorClass(errStr, self.decode_error_status)
        return str(bytes_[:-1], 'ascii')


class IntegerWrapperEncoder(PDUNullableFieldEncoder):
    field_name = None
    name_map = None
    value_map = None
    encoder = None
    pdu_type = None
    decodeErrorClass = PDUParseError
    decode_error_status = pdu_types.CommandStatus.ESME_RUNKNOWNERR

    def __init__(self, **kwargs):
        PDUNullableFieldEncoder.__init__(self, **kwargs)
        self.nullHex = self.encoder.nullHex
        self.field_name = kwargs.get('field_name', self.field_name)
        self.decodeErrorClass = kwargs.get('decodeErrorClass', self.decodeErrorClass)
        self.decode_error_status = kwargs.get('decode_error_status', self.decode_error_status)

    def _encode(self, value) -> bytes:
        name = str(value)
        if name not in self.name_map:
            raise ValueError("Unknown %s name %s" % (self.field_name, name))
        intVal = self.name_map[name]
        return self.encoder.encode(intVal)

    def _read(self, file: io.BytesIO) -> bytes:
        return self.encoder._read(file)

    def _decode(self, bytes_: bytes):
        int_val = self.encoder._decode(bytes_)
        if int_val not in self.value_map:
            errStr = "Unknown %s value %s" % (self.field_name, hex(int_val))
            raise self.decodeErrorClass(errStr, self.decode_error_status)
        name = self.value_map[int_val]
        return getattr(self.pdu_type, name)


class CommandIdEncoder(IntegerWrapperEncoder):
    field_name = 'command_id'
    name_map = constants.command_id_name_map
    value_map = constants.command_id_value_map
    encoder = Int4Encoder()
    pdu_type = pdu_types.CommandId
    decodeErrorClass = PDUCorruptError
    decode_error_status = pdu_types.CommandStatus.ESME_RINVCMDID


class CommandStatusEncoder(Int4Encoder):
    nullable = False

    def _encode(self, value) -> bytes:
        name = str(value)
        if name not in constants.command_status_name_map:
            raise ValueError("Unknown command_status name %s" % name)
        intval = constants.command_status_name_map[name]
        return Int4Encoder().encode(intval)

    def _decode(self, bytes_: bytes):
        intval = Int4Encoder()._decode(bytes_)
        if intval not in constants.command_status_value_map:
            raise PDUParseError("Unknown command_status %s" % intval,
                                pdu_types.CommandStatus.ESME_RUNKNOWNERR)
        name = constants.command_status_value_map[intval]['name']
        return getattr(pdu_types.CommandStatus, name)


class TagEncoder(IntegerWrapperEncoder):
    field_name = 'tag'
    name_map = constants.tag_name_map
    value_map = constants.tag_value_map
    encoder = Int2Encoder()
    pdu_type = pdu_types.Tag
    decode_error_status = pdu_types.CommandStatus.ESME_RINVOPTPARSTREAM


class EsmClassEncoder(Int1Encoder):
    modeMask = 0x03
    typeMask = 0x3c
    gsmFeaturesMask = 0xc0

    def _encode(self, esmClass) -> bytes:
        modeName = str(esmClass.mode)
        typeName = str(esmClass.type)
        gsmFeatureNames = [str(f) for f in esmClass.gsm_features]

        if modeName not in constants.esm_class_mode_name_map:
            raise ValueError("Unknown esm_class mode name %s" % modeName)
        if typeName not in constants.esm_class_type_name_map:
            raise ValueError("Unknown esm_class type name %s" % typeName)
        for featureName in gsmFeatureNames:
            if featureName not in constants.esm_class_gsm_features_name_map:
                raise ValueError("Unknown esm_class GSM feature name %s" % featureName)

        modeVal = constants.esm_class_mode_name_map[modeName]
        typeVal = constants.esm_class_type_name_map[typeName]
        gsmFeatureVals = [constants.esm_class_gsm_features_name_map[fName] for fName in
                          gsmFeatureNames]

        intVal = modeVal | typeVal
        for fVal in gsmFeatureVals:
            intVal |= fVal

        return Int1Encoder().encode(intVal)

    def _decode(self, bytes_: bytes):
        intVal = Int1Encoder()._decode(bytes_)
        modeVal = intVal & self.modeMask
        typeVal = intVal & self.typeMask
        gsmFeaturesVal = intVal & self.gsmFeaturesMask

        if modeVal not in constants.esm_class_mode_value_map:
            raise PDUParseError("Unknown esm_class mode %s" % modeVal,
                                pdu_types.CommandStatus.ESME_RINVESMCLASS)
        if typeVal not in constants.esm_class_type_value_map:
            raise PDUParseError("Unknown esm_class type %s" % typeVal,
                                pdu_types.CommandStatus.ESME_RINVESMCLASS)

        modeName = constants.esm_class_mode_value_map[modeVal]
        typeName = constants.esm_class_type_value_map[typeVal]
        gsmFeatureNames = [constants.esm_class_gsm_features_value_map[fVal] for fVal in
                           list(constants.esm_class_gsm_features_value_map.keys()) if
                           fVal & gsmFeaturesVal]

        mode = getattr(pdu_types.EsmClassMode, modeName)
        type = getattr(pdu_types.EsmClassType, typeName)
        gsm_features = [getattr(pdu_types.EsmClassGsmFeatures, fName) for fName in
                        gsmFeatureNames]

        return pdu_types.EsmClass(mode, type, gsm_features)


class RegisteredDeliveryEncoder(Int1Encoder):
    receiptMask = 0x03
    smeOriginatedAcksMask = 0x0c
    intermediateNotificationMask = 0x10

    def _encode(self, registeredDelivery) -> bytes:
        receiptName = str(registeredDelivery.receipt)
        smeOriginatedAckNames = [str(a) for a in registeredDelivery.sme_originated_acks]

        if receiptName not in constants.registered_delivery_receipt_name_map:
            raise ValueError("Unknown registered_delivery receipt name %s" % receiptName)
        for ackName in smeOriginatedAckNames:
            if ackName not in constants.registered_delivery_sme_originated_acks_name_map:
                raise ValueError(
                    "Unknown registered_delivery SME orginated ack name %s" % ackName)

        receiptVal = constants.registered_delivery_receipt_name_map[receiptName]
        smeOriginatedAckVals = [
            constants.registered_delivery_sme_originated_acks_name_map[ackName] for
            ackName in smeOriginatedAckNames]
        intermediateNotificationVal = 0
        if registeredDelivery.intermediate_notification:
            intermediateNotificationVal = self.intermediateNotificationMask

        intVal = receiptVal | intermediateNotificationVal
        for aVal in smeOriginatedAckVals:
            intVal |= aVal

        return Int1Encoder().encode(intVal)

    def _decode(self, bytes_: bytes):
        intVal = Int1Encoder()._decode(bytes_)
        receiptVal = intVal & self.receiptMask
        smeOriginatedAcksVal = intVal & self.smeOriginatedAcksMask
        intermediateNotificationVal = intVal & self.intermediateNotificationMask

        if receiptVal not in constants.registered_delivery_receipt_value_map:
            raise PDUParseError("Unknown registered_delivery receipt %s" % receiptVal,
                                pdu_types.CommandStatus.ESME_RINVREGDLVFLG)

        receiptName = constants.registered_delivery_receipt_value_map[receiptVal]
        smeOriginatedAckNames = [
            constants.registered_delivery_sme_originated_acks_value_map[aVal] for aVal in
            list(constants.registered_delivery_sme_originated_acks_value_map.keys()) if
            aVal & smeOriginatedAcksVal]

        receipt = getattr(pdu_types.RegisteredDeliveryReceipt, receiptName)
        sme_originated_acks = [
            getattr(pdu_types.RegisteredDeliverySmeOriginatedAcks, aName)
            for aName in smeOriginatedAckNames]
        intermediate_notification = False
        if intermediateNotificationVal:
            intermediate_notification = True

        return pdu_types.RegisteredDelivery(receipt, sme_originated_acks,
                                            intermediate_notification)


class DataCodingEncoder(Int1Encoder):
    schemeMask = 0xf0
    schemeDataMask = 0x0f
    gsmMsgCodingMask = 0x04
    gsmMsgClassMask = 0x03

    def _encode(self, dataCoding) -> bytes:
        return Int1Encoder().encode(self._encodeAsInt(dataCoding))

    def _encodeAsInt(self, dataCoding):
        if dataCoding.scheme == pdu_types.DataCodingScheme.RAW:
            return dataCoding.scheme_data
        if dataCoding.scheme == pdu_types.DataCodingScheme.DEFAULT:
            return self._encodeDefaultSchemeAsInt(dataCoding)
        return self._encodeSchemeAsInt(dataCoding)

    def _encodeDefaultSchemeAsInt(self, dataCoding):
        defaultName = str(dataCoding.scheme_data)
        if defaultName not in constants.data_coding_default_name_map:
            raise ValueError("Unknown data_coding default name %s" % defaultName)
        return constants.data_coding_default_name_map[defaultName]

    def _encodeSchemeAsInt(self, dataCoding):
        schemeVal = self._encodeSchemeNameAsInt(dataCoding)
        schemeDataVal = self._encodeSchemeDataAsInt(dataCoding)
        return schemeVal | schemeDataVal

    def _encodeSchemeNameAsInt(self, dataCoding):
        schemeName = str(dataCoding.scheme)
        if schemeName not in constants.data_coding_scheme_name_map:
            raise ValueError("Unknown data_coding scheme name %s" % schemeName)
        return constants.data_coding_scheme_name_map[schemeName]

    def _encodeSchemeDataAsInt(self, dataCoding):
        if dataCoding.scheme == pdu_types.DataCodingScheme.GSM_MESSAGE_CLASS:
            return self._encodeGsmMsgSchemeDataAsInt(dataCoding)
        raise ValueError("Unknown data coding scheme %s" % dataCoding.scheme)

    def _encodeGsmMsgSchemeDataAsInt(self, dataCoding):
        msgCodingName = str(dataCoding.scheme_data.msg_coding)
        msgClassName = str(dataCoding.scheme_data.msg_class)

        if msgCodingName not in constants.data_coding_gsm_message_coding_name_map:
            raise ValueError("Unknown data_coding gsm msg coding name %s" % msgCodingName)
        if msgClassName not in constants.data_coding_gsm_message_class_name_map:
            raise ValueError("Unknown data_coding gsm msg class name %s" % msgClassName)

        msgCodingVal = constants.data_coding_gsm_message_coding_name_map[msgCodingName]
        msgClassVal = constants.data_coding_gsm_message_class_name_map[msgClassName]
        return msgCodingVal | msgClassVal

    def _decode(self, bytes_: bytes):
        int_val = Int1Encoder()._decode(bytes_)
        scheme = self._decodeScheme(int_val)
        scheme_data = self._decodeSchemeData(scheme, int_val)
        return pdu_types.DataCoding(scheme, scheme_data)

    def _decodeScheme(self, int_val):
        schemeVal = int_val & self.schemeMask
        if schemeVal in constants.data_coding_scheme_value_map:
            schemeName = constants.data_coding_scheme_value_map[schemeVal]
            return getattr(pdu_types.DataCodingScheme, schemeName)

        if int_val in constants.data_coding_default_value_map:
            return pdu_types.DataCodingScheme.DEFAULT

        return pdu_types.DataCodingScheme.RAW

    def _decodeSchemeData(self, scheme, intVal):
        if scheme == pdu_types.DataCodingScheme.RAW:
            return intVal
        if scheme == pdu_types.DataCodingScheme.DEFAULT:
            return self._decodeDefaultSchemeData(intVal)
        if scheme == pdu_types.DataCodingScheme.GSM_MESSAGE_CLASS:
            schemeDataVal = intVal & self.schemeDataMask
            return self._decodeGsmMsgSchemeData(schemeDataVal)
        raise ValueError("Unexpected data coding scheme %s" % scheme)

    def _decodeDefaultSchemeData(self, intVal):
        if intVal not in constants.data_coding_default_value_map:
            raise ValueError("Unknown data_coding default value %s" % intVal)
        defaultName = constants.data_coding_default_value_map[intVal]
        return getattr(pdu_types.DataCodingDefault, defaultName)

    def _decodeGsmMsgSchemeData(self, schemeDataVal):
        msgCodingVal = schemeDataVal & self.gsmMsgCodingMask
        msgClassVal = schemeDataVal & self.gsmMsgClassMask

        if msgCodingVal not in constants.data_coding_gsm_message_coding_value_map:
            raise ValueError("Unknown data_coding gsm msg coding value %s" % msgCodingVal)
        if msgClassVal not in constants.data_coding_gsm_message_class_value_map:
            raise ValueError("Unknown data_coding gsm msg class value %s" % msgClassVal)

        msgCodingName = constants.data_coding_gsm_message_coding_value_map[msgCodingVal]
        msgClassName = constants.data_coding_gsm_message_class_value_map[msgClassVal]

        msg_coding = getattr(pdu_types.DataCodingGsmMsgCoding, msgCodingName)
        msg_class = getattr(pdu_types.DataCodingGsmMsgClass, msgClassName)
        return pdu_types.DataCodingGsmMsg(msg_coding, msg_class)


class AddrTonEncoder(IntegerWrapperEncoder):
    field_name = 'addr_ton'
    name_map = constants.addr_ton_name_map
    value_map = constants.addr_ton_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.AddrTon


class AddrNpiEncoder(IntegerWrapperEncoder):
    field_name = 'addr_npi'
    name_map = constants.addr_npi_name_map
    value_map = constants.addr_npi_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.AddrNpi


class PriorityFlagEncoder(IntegerWrapperEncoder):
    field_name = 'priority_flag'
    name_map = constants.priority_flag_name_map
    value_map = constants.priority_flag_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.PriorityFlag
    decode_error_status = pdu_types.CommandStatus.ESME_RINVPRTFLG


class ReplaceIfPresentFlagEncoder(IntegerWrapperEncoder):
    field_name = 'replace_if_present_flag'
    name_map = constants.replace_if_present_flap_name_map
    value_map = constants.replace_if_present_flap_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.ReplaceIfPresentFlag


class DestFlagEncoder(IntegerWrapperEncoder):
    nullable = False
    field_name = 'dest_flag'
    name_map = constants.dest_flag_name_map
    value_map = constants.dest_flag_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.DestFlag


class MessageStateEncoder(IntegerWrapperEncoder):
    nullable = False
    field_name = 'message_state'
    name_map = constants.message_state_name_map
    value_map = constants.message_state_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.MessageState


class CallbackNumDigitModeIndicatorEncoder(IntegerWrapperEncoder):
    nullable = False
    field_name = 'callback_num_digit_mode_indicator'
    name_map = constants.callback_num_digit_mode_indicator_name_map
    value_map = constants.callback_num_digit_mode_indicator_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.CallbackNumDigitModeIndicator
    decode_error_status = pdu_types.CommandStatus.ESME_RINVOPTPARAMVAL


class CallbackNumEncoder(OctetStringEncoder):
    digitModeIndicatorEncoder = CallbackNumDigitModeIndicatorEncoder()
    tonEncoder = AddrTonEncoder()
    npiEncoder = AddrNpiEncoder()

    def _encode(self, callbackNum) -> bytes:
        encoded = b''
        encoded += self.digitModeIndicatorEncoder._encode(
            callbackNum.digit_mode_indicator)
        encoded += self.tonEncoder._encode(callbackNum.ton)
        encoded += self.npiEncoder._encode(callbackNum.npi)
        encoded += callbackNum.digits
        return encoded

    def _decode(self, bytes_: bytes):
        if len(bytes_) < 3:
            raise PDUParseError("Invalid callback_num size %s" % len(bytes_),
                                pdu_types.CommandStatus.ESME_RINVOPTPARAMVAL)

        digit_mode_indicator = self.digitModeIndicatorEncoder._decode(bytes_[0:1])
        ton = self.tonEncoder._decode(bytes_[1:2])
        npi = self.npiEncoder._decode(bytes_[2:3])
        digits = bytes_[3:]
        return pdu_types.CallbackNum(digit_mode_indicator, ton, npi, digits)


class SubaddressTypeTagEncoder(IntegerWrapperEncoder):
    nullable = False
    field_name = 'subaddress_type_tag'
    name_map = constants.subaddress_type_tag_name_map
    value_map = constants.subaddress_type_tag_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.SubaddressTypeTag
    decode_error_status = pdu_types.CommandStatus.ESME_RINVOPTPARAMVAL


class SubaddressEncoder(OctetStringEncoder):
    typeTagEncoder = SubaddressTypeTagEncoder()

    def _encode(self, subaddress) -> bytes:
        encoded = b''
        encoded += self.typeTagEncoder._encode(subaddress.type_tag)
        valSize = self.getSize() - 1 if self.getSize() is not None else None
        encoded += OctetStringEncoder(valSize)._encode(subaddress.value)
        return encoded

    def _decode(self, bytes_: bytes):
        if len(bytes_) < 2:
            raise PDUParseError("Invalid subaddress size %s" % len(bytes_),
                                pdu_types.CommandStatus.ESME_RINVOPTPARAMVAL)

        type_tag = self.typeTagEncoder._decode(bytes_[0:1])
        value = OctetStringEncoder(self.getSize() - 1)._decode(bytes_[1:])
        return pdu_types.Subaddress(type_tag, value)


class AddrSubunitEncoder(IntegerWrapperEncoder):
    field_name = 'addr_subunit'
    name_map = constants.addr_subunit_name_map
    value_map = constants.addr_subunit_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.AddrSubunit


class NetworkTypeEncoder(IntegerWrapperEncoder):
    field_name = 'network_type'
    name_map = constants.network_type_name_map
    value_map = constants.network_type_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.NetworkType


class BearerTypeEncoder(IntegerWrapperEncoder):
    field_name = 'bearer_type'
    name_map = constants.bearer_type_name_map
    value_map = constants.bearer_type_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.BearerType


class PayloadTypeEncoder(IntegerWrapperEncoder):
    field_name = 'payload_type'
    name_map = constants.payload_type_name_map
    value_map = constants.payload_type_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.PayloadType


class PrivacyIndicatorEncoder(IntegerWrapperEncoder):
    field_name = 'privacy_indicator'
    name_map = constants.privacy_indicator_name_map
    value_map = constants.privacy_indicator_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.PrivacyIndicator


class LanguageIndicatorEncoder(IntegerWrapperEncoder):
    field_name = 'language_indicator'
    name_map = constants.language_indicator_name_map
    value_map = constants.language_indicator_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.LanguageIndicator


class DisplayTimeEncoder(IntegerWrapperEncoder):
    field_name = 'display_time'
    name_map = constants.display_time_name_map
    value_map = constants.display_time_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.DisplayTime


class MsAvailabilityStatusEncoder(IntegerWrapperEncoder):
    field_name = 'ms_availability_status'
    name_map = constants.ms_availability_status_name_map
    value_map = constants.ms_availability_status_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.MsAvailabilityStatus


class DeliveryFailureReasonEncoder(IntegerWrapperEncoder):
    field_name = 'delivery_failure_reason'
    name_map = constants.delivery_failure_reason_name_map
    value_map = constants.delivery_failure_reason_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.DeliveryFailureReason


class MoreMessagesToSendEncoder(IntegerWrapperEncoder):
    field_name = 'more_messages_to_send'
    name_map = constants.more_messages_to_send_name_map
    value_map = constants.more_messages_to_send_value_map
    encoder = Int1Encoder()
    pdu_type = pdu_types.MoreMessagesToSend


class TimeEncoder(PDUNullableFieldEncoder):
    nullHex = b'00'
    decodeNull = True
    encoder = COctetStringEncoder(17)
    decodeErrorClass = PDUParseError
    decode_error_status = pdu_types.CommandStatus.ESME_RUNKNOWNERR

    def __init__(self, **kwargs):
        PDUNullableFieldEncoder.__init__(self, **kwargs)
        self.decodeErrorClass = kwargs.get('decodeErrorClass', self.decodeErrorClass)
        self.decode_error_status = kwargs.get('decode_error_status', self.decode_error_status)
        self.encoder.decode_error_status = self.decode_error_status

    def _encode(self, time) -> bytes:
        str = smpp_time.unparse(time)
        return self.encoder._encode(str)

    def _read(self, file: io.BytesIO) -> bytes:
        return self.encoder._read(file)

    def _decode(self, bytes_: bytes):
        timeStr = self.encoder._decode(bytes_)
        try:
            return smpp_time.parse(timeStr)
        except Exception as e:
            raise self.decodeErrorClass(str(e), self.decode_error_status)


class ShortMessageEncoder(IEncoder):
    smLengthEncoder = Int1Encoder(max=254)

    def encode(self, shortMessage) -> bytes:
        if shortMessage is None:
            shortMessage = b''
        smLength = len(shortMessage)
        return (
                self.smLengthEncoder.encode(smLength) +
                OctetStringEncoder(smLength).encode(shortMessage)
        )

    def decode(self, file: io.BytesIO):
        smLength = self.smLengthEncoder.decode(file)
        return OctetStringEncoder(smLength).decode(file)


class OptionEncoder(IEncoder):

    def __init__(self):
        from smpp.pdu.pdu_types import Tag as T
        self.length = None
        self.options = {
            T.dest_addr_subunit: AddrSubunitEncoder(),
            T.source_addr_subunit: AddrSubunitEncoder(),
            T.dest_network_type: NetworkTypeEncoder(),
            T.source_network_type: NetworkTypeEncoder(),
            T.dest_bearer_type: BearerTypeEncoder(),
            T.source_bearer_type: BearerTypeEncoder(),
            T.dest_telematics_id: Int2Encoder(),
            T.source_telematics_id: Int2Encoder(),
            T.qos_time_to_live: Int4Encoder(),
            T.payload_type: PayloadTypeEncoder(),
            T.additional_status_info_text: COctetStringEncoder(256),
            T.receipted_message_id: COctetStringEncoder(65),
            # T.ms_msg_wait_facilities: TODO(),
            T.privacy_indicator: PrivacyIndicatorEncoder(),
            T.source_subaddress: SubaddressEncoder(self.getLength),
            T.dest_subaddress: SubaddressEncoder(self.getLength),
            T.user_message_reference: Int2Encoder(),
            T.user_response_code: Int1Encoder(),
            T.language_indicator: LanguageIndicatorEncoder(),
            T.source_port: Int2Encoder(),
            T.destination_port: Int2Encoder(),
            T.sar_msg_ref_num: Int2Encoder(),
            T.sar_total_segments: Int1Encoder(),
            T.sar_segment_seqnum: Int1Encoder(),
            T.sc_interface_version: Int1Encoder(),
            T.display_time: DisplayTimeEncoder(),
            # T.ms_validity: MsValidityEncoder(),
            # T.dpf_result: DpfResultEncoder(),
            # T.set_dpf: SetDpfEncoder(),
            T.ms_availability_status: MsAvailabilityStatusEncoder(),
            # T.network_error_code: NetworkErrorCodeEncoder(),
            T.message_payload: OctetStringEncoder(self.getLength),
            T.delivery_failure_reason: DeliveryFailureReasonEncoder(),
            T.more_messages_to_send: MoreMessagesToSendEncoder(),
            T.message_state: MessageStateEncoder(),
            T.callback_num: CallbackNumEncoder(self.getLength),
            # T.callback_num_pres_ind: CallbackNumPresIndEncoder(),
            # T.callback_num_atag: CallbackNumAtag(),
            T.number_of_messages: Int1Encoder(max=99),
            T.sms_signal: OctetStringEncoder(self.getLength),
            T.alert_on_message_delivery: EmptyEncoder(),
            # T.its_reply_type: ItsReplyTypeEncoder(),
            # T.its_session_info: ItsSessionInfoEncoder(),
            # T.ussd_service_op: UssdServiceOpEncoder(),
        }

    def getLength(self):
        return self.length

    def encode(self, option) -> bytes:
        if option.tag not in self.options:
            raise ValueError("Unknown option %s" % str(option))
        encoder = self.options[option.tag]
        encodedValue = encoder.encode(option.value)
        length = len(encodedValue)
        return b''.join([
            TagEncoder().encode(option.tag),
            Int2Encoder().encode(length),
            encodedValue,
        ])

    def decode(self, file: io.BytesIO):
        tag = TagEncoder().decode(file)
        self.length = Int2Encoder().decode(file)
        if tag not in self.options:
            raise PDUParseError("Optional param %s unknown" % tag,
                                pdu_types.CommandStatus.ESME_ROPTPARNOTALLWD)
        encoder = self.options[tag]
        iBeforeDecode = file.tell()
        try:
            value = encoder.decode(file)
        except PDUParseError as e:
            e.status = pdu_types.CommandStatus.ESME_RINVOPTPARAMVAL
            raise e

        iAfterDecode = file.tell()
        parseLen = iAfterDecode - iBeforeDecode
        if parseLen != self.length:
            raise PDUParseError("Invalid option length: labeled [%d] but parsed [%d]" % (
                self.length, parseLen), pdu_types.CommandStatus.ESME_RINVPARLEN)
        return pdu_types.Option(tag, value)


class PDUEncoder(IEncoder):
    HEADER_LEN = 16

    HeaderEncoders = {
        'command_length': Int4Encoder(),
        'command_id': CommandIdEncoder(),
        'command_status': CommandStatusEncoder(),
        # the spec says max=0x7FFFFFFF but vendors don't respect this
        'sequence_number': Int4Encoder(min=0x00000001),
    }
    HeaderParams = [
        'command_length',
        'command_id',
        'command_status',
        'sequence_number',
    ]

    DefaultRequiredParamEncoders = {
        'system_id': COctetStringEncoder(16,
                                         decode_error_status=pdu_types.CommandStatus.ESME_RINVSYSID),
        'password': COctetStringEncoder(9,
                                        decode_error_status=pdu_types.CommandStatus.ESME_RINVPASWD),
        'system_type': COctetStringEncoder(13),
        'interface_version': Int1Encoder(),
        'addr_ton': AddrTonEncoder(),
        'addr_npi': AddrNpiEncoder(),
        'address_range': COctetStringEncoder(41),
        'service_type': COctetStringEncoder(6,
                                            decode_error_status=pdu_types.CommandStatus.ESME_RINVSERTYP),
        'source_addr_ton': AddrTonEncoder(field_name='source_addr_ton',
                                          decode_error_status=pdu_types.CommandStatus.ESME_RINVSRCTON),
        'source_addr_npi': AddrNpiEncoder(field_name='source_addr_npi',
                                          decode_error_status=pdu_types.CommandStatus.ESME_RINVSRCNPI),
        'source_addr': COctetStringEncoder(21,
                                           decode_error_status=pdu_types.CommandStatus.ESME_RINVSRCADR),
        'dest_addr_ton': AddrTonEncoder(field_name='dest_addr_ton',
                                        decode_error_status=pdu_types.CommandStatus.ESME_RINVDSTTON),
        'dest_addr_npi': AddrNpiEncoder(field_name='dest_addr_npi',
                                        decode_error_status=pdu_types.CommandStatus.ESME_RINVDSTNPI),
        'destination_addr': COctetStringEncoder(21,
                                                decode_error_status=pdu_types.CommandStatus.ESME_RINVDSTADR),
        'esm_class': EsmClassEncoder(),
        'esme_addr_ton': AddrTonEncoder(field_name='esme_addr_ton'),
        'esme_addr_npi': AddrNpiEncoder(field_name='esme_addr_npi'),
        'esme_addr': COctetStringEncoder(65),
        'protocol_id': Int1Encoder(),
        'priority_flag': PriorityFlagEncoder(),
        'schedule_delivery_time': TimeEncoder(
            decode_error_status=pdu_types.CommandStatus.ESME_RINVSCHED),
        'validity_period': TimeEncoder(
            decode_error_status=pdu_types.CommandStatus.ESME_RINVEXPIRY),
        'registered_delivery': RegisteredDeliveryEncoder(),
        'replace_if_present_flag': ReplaceIfPresentFlagEncoder(),
        'data_coding': DataCodingEncoder(),
        'sm_default_msg_id': Int1Encoder(min=1, max=254,
                                         decode_error_status=pdu_types.CommandStatus.ESME_RINVDFTMSGID),
        'short_message': ShortMessageEncoder(),
        'message_id': COctetStringEncoder(65,
                                          decode_error_status=pdu_types.CommandStatus.ESME_RINVMSGID),
        # 'number_of_dests': Int1Encoder(max=254),
        # 'no_unsuccess': Int1Encoder(),
        # 'dl_name': COctetStringEncoder(21),
        'message_state': MessageStateEncoder(),
        'final_date': TimeEncoder(),
        'error_code': Int1Encoder(decodeNull=True),
    }

    CustomRequiredParamEncoders = {
        pdu_types.CommandId.alert_notification: {
            'source_addr': COctetStringEncoder(65,
                                               decode_error_status=pdu_types.CommandStatus.ESME_RINVSRCADR),
        },
        pdu_types.CommandId.data_sm: {
            'source_addr': COctetStringEncoder(65,
                                               decode_error_status=pdu_types.CommandStatus.ESME_RINVSRCADR),
            'destination_addr': COctetStringEncoder(65,
                                                    decode_error_status=pdu_types.CommandStatus.ESME_RINVDSTADR),
        },
        pdu_types.CommandId.deliver_sm: {
            'schedule_delivery_time': TimeEncoder(requireNull=True,
                                                  decode_error_status=pdu_types.CommandStatus.ESME_RINVSCHED),
            'validity_period': TimeEncoder(requireNull=True,
                                           decode_error_status=pdu_types.CommandStatus.ESME_RINVEXPIRY),
        },
        pdu_types.CommandId.deliver_sm_resp: {
            'message_id': COctetStringEncoder(decodeNull=True, requireNull=True,
                                              decode_error_status=pdu_types.CommandStatus.ESME_RINVMSGID),
        }
    }

    def __init__(self):
        self.optionEncoder = OptionEncoder()

    def getRequiredParamEncoders(self, pdu):
        if pdu.id in self.CustomRequiredParamEncoders:
            return dict(list(self.DefaultRequiredParamEncoders.items()) + list(
                self.CustomRequiredParamEncoders[pdu.id].items()))
        return self.DefaultRequiredParamEncoders

    def encode(self, pdu) -> bytes:
        body = self.encodeBody(pdu)
        return self.encodeHeader(pdu, body) + body

    def decode(self, file: io.BytesIO):
        iBeforeDecode = file.tell()
        headerParams = self.decodeHeader(file)
        pduKlass = operations.get_pdu_class(headerParams['command_id'])
        pdu = pduKlass(headerParams['sequence_number'], headerParams['command_status'])
        self.decodeBody(file, pdu, headerParams['command_length'] - self.HEADER_LEN)

        iAfterDecode = file.tell()
        parsedLen = iAfterDecode - iBeforeDecode
        if parsedLen != headerParams['command_length']:
            raise PDUCorruptError("Invalid command length: expected %d, parsed %d" % (
                headerParams['command_length'], parsedLen),
                                  pdu_types.CommandStatus.ESME_RINVCMDLEN)

        return pdu

    def decodeHeader(self, file: io.BytesIO):
        headerParams = self.decodeRequiredParams(self.HeaderParams, self.HeaderEncoders,
                                                 file)
        if headerParams['command_length'] < self.HEADER_LEN:
            raise PDUCorruptError(
                "Invalid command_length %d" % headerParams['command_length'],
                pdu_types.CommandStatus.ESME_RINVCMDLEN)
        return headerParams

    def decodeBody(self, file, pdu, bodyLength):
        mandatory_params = {}
        optional_params = {}

        # Some PDU responses have no defined body when the status is not 0
        #    c.f. 4.1.4. "BIND_RECEIVER_RESP"
        #    c.f. 4.4.2. SMPP PDU Definition "SUBMIT_SM_RESP"
        if pdu.status != pdu_types.CommandStatus.ESME_ROK:
            if pdu.no_body_on_error:
                return

        iBeforeMParams = file.tell()
        if len(pdu.mandatory_params) > 0:
            mandatory_params = self.decodeRequiredParams(pdu.mandatory_params,
                                                         self.getRequiredParamEncoders(
                                                             pdu), file)
        iAfterMParams = file.tell()
        mParamsLen = iAfterMParams - iBeforeMParams
        if len(pdu.optional_params) > 0:
            optional_params = self.decodeOptionalParams(pdu.optional_params, file,
                                                        bodyLength - mParamsLen)
        pdu.params = dict(list(mandatory_params.items()) + list(optional_params.items()))

    def encodeBody(self, pdu) -> bytes:
        body = b''

        # Some PDU responses have no defined body when the status is not 0
        #    c.f. 4.1.4. "BIND_RECEIVER_RESP"
        #    c.f. 4.4.2. SMPP PDU Definition "SUBMIT_SM_RESP"
        if pdu.status != pdu_types.CommandStatus.ESME_ROK:
            if pdu.no_body_on_error:
                return body

        for paramName in pdu.mandatory_params:
            if paramName not in pdu.params:
                raise ValueError("Missing required parameter: %s" % paramName)

        body += self.encodeRequiredParams(pdu.mandatory_params,
                                          self.getRequiredParamEncoders(pdu), pdu.params)
        body += self.encodeOptionalParams(pdu.optional_params, pdu.params)
        return body

    def encodeHeader(self, pdu, body) -> bytes:
        cmdLength = len(body) + self.HEADER_LEN
        headerParams = {
            'command_length': cmdLength,
            'command_id': pdu.id,
            'command_status': pdu.status,
            'sequence_number': pdu.sequence_number,
        }
        header = self.encodeRequiredParams(self.HeaderParams, self.HeaderEncoders,
                                           headerParams)
        assert len(header) == self.HEADER_LEN
        return header

    def encodeOptionalParams(self, optional_params, params) -> bytes:
        result = b''
        for paramName in optional_params:
            if paramName in params:
                tag = getattr(pdu_types.Tag, paramName)
                value = params[paramName]
                result += self.optionEncoder.encode(pdu_types.Option(tag, value))
        return result

    def decodeOptionalParams(self, paramList, file, optionsLength):
        optional_params = {}
        iBefore = file.tell()
        while file.tell() - iBefore < optionsLength:
            option = self.optionEncoder.decode(file)
            optionName = str(option.tag)
            if optionName not in paramList:
                raise PDUParseError("Invalid option %s" % optionName,
                                    pdu_types.CommandStatus.ESME_ROPTPARNOTALLWD)
            optional_params[optionName] = option.value
        return optional_params

    def encodeRequiredParams(self, paramList, encoderMap, params):
        return b''.join(
            [encoderMap[paramName].encode(params[paramName]) for paramName in paramList]
        )

    def decodeRequiredParams(self, paramList, encoderMap, file):
        params = {}
        for paramName in paramList:
            params[paramName] = encoderMap[paramName].decode(file)
        return params
