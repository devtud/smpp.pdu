# SMPPPDU (Forked from [smpp.pdu](https://github.com/mozes/smpp.pdu))

smpppdu is a Python3 library for parsing Protocol Data Units (PDUs) in SMPP protocol

http://www.nowsms.com/discus/messages/1/24856.html 

## Install

```bash
$ pip install smpppdu
```

## Examples

### Decoding (parsing) PDUs

```python
import binascii
import io

from smpp.pdu.pdu_encoding import PDUEncoder

hex = '0000004d00000005000000009f88f12441575342440001013136353035353531323334000101313737333535353430373000000000000000000300117468657265206973206e6f2073706f6f6e'
binary = binascii.a2b_hex(hex)
file = io.BytesIO(binary)

pdu = PDUEncoder().decode(file)
print(f"PDU: {pdu}")

# Prints the following:
#
# PDU: PDU [command: deliver_sm, sequence_number: 2676551972, command_status: ESME_ROK
# service_type: AWSBD
# source_addr_ton: INTERNATIONAL
# source_addr_npi: ISDN
# source_addr: 16505551234
# dest_addr_ton: INTERNATIONAL
# dest_addr_npi: ISDN
# destination_addr: 17735554070
# esm_class: EsmClass[mode: DEFAULT, type: DEFAULT, gsmFeatures: set()]
# protocol_id: 0
# priority_flag: LEVEL_0
# schedule_delivery_time: None
# validity_period: None
# registered_delivery: RegisteredDelivery[receipt: NO_SMSC_DELIVERY_RECEIPT_REQUESTED, smeOriginatedAcks: set(), intermediateNotification: False]
# replace_if_present_flag: DO_NOT_REPLACE
# data_coding: DataCoding[scheme: DEFAULT, schemeData: LATIN_1]
# sm_default_msg_id: None
# short_message: b'there is no spoon'
# ]
```

### Creating and encoding PDUs

```python
import binascii

from smpp.pdu.pdu_types import (
    AddrTon, AddrNpi, EsmClass, EsmClassMode, EsmClassType, PriorityFlag, 
    RegisteredDelivery, RegisteredDeliveryReceipt, ReplaceIfPresentFlag,
    DataCoding, DataCodingScheme, DataCodingGsmMsg, DataCodingGsmMsgCoding,
    DataCodingGsmMsgClass
)
from smpp.pdu.operations import SubmitSM
from smpp.pdu.pdu_encoding import PDUEncoder

pdu = SubmitSM(9284,
    service_type='',
    source_addr_ton=AddrTon.ALPHANUMERIC,
    source_addr_npi=AddrNpi.UNKNOWN,
    source_addr='mobileway',
    dest_addr_ton=AddrTon.INTERNATIONAL,
    dest_addr_npi=AddrNpi.ISDN,
    destination_addr='1208230',
    esm_class=EsmClass(EsmClassMode.DEFAULT, EsmClassType.DEFAULT),
    protocol_id=0,
    priority_flag=PriorityFlag.LEVEL_0,
    registered_delivery=RegisteredDelivery(
        RegisteredDeliveryReceipt.SMSC_DELIVERY_RECEIPT_REQUESTED
    ),
    replace_if_present_flag=ReplaceIfPresentFlag.DO_NOT_REPLACE,
    data_coding=DataCoding(
        DataCodingScheme.GSM_MESSAGE_CLASS, 
        DataCodingGsmMsg(
            DataCodingGsmMsgCoding.DEFAULT_ALPHABET, 
            DataCodingGsmMsgClass.CLASS_2
        )
    ),
    short_message=b'HELLO',
)
print(f"PDU: {pdu}")

binary = PDUEncoder().encode(pdu)
hexStr = binascii.b2a_hex(binary)
print(f"HEX: {hexStr}")

# Prints the following:
#
# PDU: PDU [command: submit_sm, sequence_number: 9284, command_status: ESME_ROK
# service_type: 
# source_addr_ton: ALPHANUMERIC
# source_addr_npi: UNKNOWN
# source_addr: mobileway
# dest_addr_ton: INTERNATIONAL
# dest_addr_npi: ISDN
# destination_addr: 1208230
# esm_class: EsmClass[mode: DEFAULT, type: DEFAULT, gsmFeatures: set()]
# protocol_id: 0
# priority_flag: LEVEL_0
# schedule_delivery_time: None
# validity_period: None
# registered_delivery: RegisteredDelivery[receipt: SMSC_DELIVERY_RECEIPT_REQUESTED, smeOriginatedAcks: set(), intermediateNotification: False]
# replace_if_present_flag: DO_NOT_REPLACE
# data_coding: DataCoding[scheme: GSM_MESSAGE_CLASS, schemeData: DataCodingGsmMsg[msgCoding: DEFAULT_ALPHABET, msgClass: CLASS_2]]
# sm_default_msg_id: None
# short_message: b'HELLO'
# ]
# HEX: b'000000360000000400000000000024440005006d6f62696c65776179000101313230383233300000000000000100f2000548454c4c4f'
```
