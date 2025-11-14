#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from functools import cmp_to_key
from dataclasses import dataclass
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

CAM_TABLE = {}
VLAN_TABLE = []
PRIO = 0
TIMER = True
SECONDS = 0
SWITCH_MAC = b'\xff' * 6
interfaces = 0
LINK_COST = 19
PORT_MODES = []
IS_RB = True
BID = b'\x00'
RBID = b'\x00'
PORTS = []
PPDU_PORTS = []
num_interfaces = 0
NON_ROOT_SET = False
CONFIG_OK = False

@dataclass
class Ppdu:
    R: bytes
    c: int
    T: bytes
    p: int
    q: int

def check_ports():
    global PORTS, BID, RBID, PPDU_PORTS

    optimal = True
    min_cost = -1

    for i in interfaces:
        if VLAN_TABLE[i] == "T":
            if PPDU_PORTS[i] != None:
                if PPDU_PORTS[i].R != RBID:
                    PPDU_PORTS[i] = None
                    PORTS[i] = None
                    optimal = False
                    continue

                if min_cost == -1 or PPDU_PORTS[min_cost].c > PPDU_PORTS[i].c:
                    min_cost = i

                print("a:", BID, "b:", PPDU_PORTS[i].T)
                if cmp_bid(BID, PPDU_PORTS[i].T) > 0:
                    PORTS[i] = "b"
                else:
                    PORTS[i] = "d"

    if min_cost > -1 and not IS_RB:
        PORTS[min_cost] = "r"
    else:
        optimal = False

    return optimal

def add_new_ppdu(interface, new_ppdu):
    global PPDU_PORTS

    if PPDU_PORTS[interface] == None:
        PPDU_PORTS[interface] = new_ppdu
        return True

    #if PPDU_PORTS[interface].R != new_ppdu.R:
     #   PPDU_PORTS[interface] = new_ppdu
      #  return

    if stp_cmp(PPDU_PORTS[interface], new_ppdu) > 0:
        PPDU_PORTS[interface] = new_ppdu
        return True

    return False

def interpret_ppdu(interface, data, length):
    global PORTS, PPDU_PORTS, PORT_MODES, RBID, BID, IS_RB, NON_ROOT_SET, CONFIG_OK
    PPDU_LEN = 56

    if not length == PPDU_LEN:
        return 

    src_mac, rbid, cost, bid, port, seq = parse_ppdu_frame(data)

    if src_mac == SWITCH_MAC:
        return

    RBID = check_and_change_rbid(RBID, rbid)
    if BID != RBID:
        IS_RB = False
        if not NON_ROOT_SET:
            NON_ROOT_SET = True
            PORTS = [None] * num_interfaces
    else:
        CONFIG_OK = True
        print("config is ok")
        PORT_MODES = ["f"] * num_interfaces
        return

    if rbid != RBID:
        return

    new_ppdu = Ppdu(rbid, cost + LINK_COST, bid, port, interface)

    add_new_ppdu(interface, new_ppdu)

    if check_ports():
        if not CONFIG_OK:
            CONFIG_OK = True
            print("config is ok")
            PORT_MODES = ["f"] * num_interfaces
    else:
        if CONFIG_OK:
            CONFIG_OK = False
            print("config not ok")
            PORT_MODES = ["b"] * num_interfaces

    for i in interfaces:
        if VLAN_TABLE[i] == "T":
            if i != interface:
                if not CONFIG_OK:
                    frame = create_ppdu_frame(src_mac, seq + 1, rbid, cost + LINK_COST, BID, i)
                    send_to_link(i, len(frame), frame)
                elif CONFIG_OK and PORTS[i] != "r":
                    frame = create_ppdu_frame(src_mac, seq + 1, rbid, cost + LINK_COST, BID, i)
                    send_to_link(i, len(frame), frame)



    print(PORTS)
    print(PPDU_PORTS)


def parse_config(switch_id):
    global PRIO
    with open("./configs/switch{}.cfg".format(switch_id), "r", encoding="utf-8") as infile:
        PRIO = int(infile.readline(), 10)
        for lines in infile.readlines():
            lines = lines.split(" ")
            VLAN_TABLE.append(lines[1][:-1])

    print("prio:", PRIO)
    print(VLAN_TABLE)

def create_bid(prio, mac):
    return struct.pack(">h", prio) + mac

def timer_func():
    global TIMER, SECONDS
    time.sleep(SECONDS)
    TIMER = False
    print("Timer stopped")

def ppdu_transmitter():
    global IS_RB
    seq_number = 0
    while True:
        if IS_RB:
            for i in interfaces:
                if VLAN_TABLE[i] == "T":
                    ppdu_frame = create_ppdu_frame(SWITCH_MAC, seq_number, BID, 0, BID, i)
                    seq_number += 1
                    send_to_link(i, len(ppdu_frame), ppdu_frame)
        time.sleep(1)


def start_timer(seconds):
    global TIMER, SECONDS
    TIMER = True
    SECONDS = seconds
    timer = threading.Thread(target=timer_func)
    timer.start()

def create_port_id(pid):
    return (128 << 4) | pid

def extract_port_id(pid):
    pid = int.from_bytes(pid, "big")
    return pid ^ (128 << 4)

def create_ppdu_frame(src_mac, seq_number, rbid, root_path_cost, bid, pid):
    root_path_cost = int(root_path_cost)
    pid = int(pid)
    dest_mac = b"\x01\x80\xc2\x00\x00\x00"

    llc_header = b'\x42\x42\x03'

    # ppdu header
    ppdu_header = b'\x00\x02\x00\x80' + struct.pack(">i", seq_number % 100)

    ppdu_config_last = struct.pack(">hhhhh",
                       create_port_id(pid),
                       0, # message age
                       40, # max age
                       2, # hello time
                       4) # forward delay

    ppdu_config = b'\x00' + rbid + struct.pack(">i", root_path_cost) + bid + ppdu_config_last

    frame_length = len(llc_header + ppdu_header + ppdu_config)
    return dest_mac + src_mac + struct.pack(">h", frame_length) + llc_header + ppdu_header + ppdu_config

def parse_ppdu_frame(frame):
    dest_mac = frame[0:6]
    src_mac = frame[6:12]

    seq_no = int.from_bytes(frame[21:25], "big")
    rbid = frame[26:34]
    root_path_cost = int.from_bytes(frame[34:38], "big")
    bid = frame[38:46]
    pid = extract_port_id(frame[46:48])

    return src_mac, rbid, root_path_cost, bid, pid, seq_no

def check_and_change_rbid(RBID, BID):
    if int.from_bytes(BID, "big") < int.from_bytes(RBID, "big"):
        return BID

    return RBID

def cmp_bid(a, b):
    return int.from_bytes(a, "big") - int.from_bytes(b, "big")


def is_unicast(mac_addr):
    return mac_addr != "ff:ff:ff:ff:ff:ff"

def is_trunk(mode):
    return VLAN_TABLE[mode] == "T"

def make_hello():
    global SWITCH_MAC
    dest_mac = b'\xff' * 6
    src_mac = SWITCH_MAC
    ether_type = b'\x08\x00'
    data = b'\xff'

    return dest_mac + src_mac + ether_type + data

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]

    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    vlan_tci = -1
    # Check for VLAN tag (0x8200 in network byte order is b'\x82\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id, vlan_tci

def create_ext_id(mac):
    sum = 0
    mac = [int("0x" + b, 16) for b in mac.split(":")]
    for b in mac:
        sum += b

    sum = sum & 0xf
    sum = sum & 0xf
    print("Nibble sum:", sum, mac)
    return sum

def stp_cmp(a, b):
    if a.c < b.c:
        return -1

    if a.c > b.c:
        return 1

    bid_cmp_res = cmp_bid(a.T, b.T)
    if bid_cmp_res < 0:
        return -1

    if bid_cmp_res > 0:
        return 1

    if a.p < b.p:
        return -1

    if a.p > b.p:
        return 1

    return a.q - b.q
    

def create_vlan_tag(ext_id, vlan_id):
    # Use EtherType = 8200h for our custom 802.1Q-like protocol.
    # PCP and DEI bits are used to extend the original VID.
    #
    # The ext_id should be the sum of all nibbles in the MAC address of the
    # host attached to the _access_ port. Ignore the overflow in the 4-bit
    # accumulator.
    #
    # NOTE: Include these 4 extensions bits only in the check for unicast
    #       frames. For multicasts, assume that you're dealing with 802.1Q.
    return struct.pack('!H', 0x8200) + \
           struct.pack('!H', ((ext_id & 0xF) << 12) | (vlan_id & 0x0FFF))

def extract_ext_id(vlan_tci):
    return (vlan_tci >> 12) & 0xf

def hello_func():
    frame = make_hello()
    print("Started Hello")
    while True:
        for i in interfaces:
            if VLAN_TABLE[i] == "T":
                send_to_link(i, len(frame), frame)
        time.sleep(1)

def main():
    global interfaces, num_interfaces
    global PORT_MODES, PORTS, PPDU_PORTS
    global IS_RB
    global BID, RBID, SWITCH_MAC
    switch_id = sys.argv[1]
    parse_config(switch_id)

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)
    PORT_MODES = ["b"] * num_interfaces

    PORTS = ["d"] * num_interfaces
    PPDU_PORTS = [None] * num_interfaces
    
    BID = create_bid(PRIO, get_switch_mac())
    RBID = BID
    SWITCH_MAC = get_switch_mac()
    print("BID:", BID)

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # Example of running a function on a separate thread.
    hello = threading.Thread(target=hello_func)
    hello.start()

    ppdu_tran = threading.Thread(target=ppdu_transmitter)
    ppdu_tran.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))

    HELLO_LEN = len(make_hello())
    PPDU_LEN = 56

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()
        print("am primit pachet")
        print(PORT_MODES)
        # switch does not listen on blocked ports
        if length == PPDU_LEN:

            print("am primit pachet ppdu")
            interpret_ppdu(interface, data, length)

        elif PORT_MODES[interface] != "b":
            print("am primit pachet")

            # skip over hello frames
            if length == HELLO_LEN:
                continue

            if PORTS[interface] == "b":
                continue

            dest_mac, src_mac, ethertype, vlan_id, vlan_tci = parse_ethernet_header(data)

            # Print the MAC src and MAC dst in human readable format
            dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
            src_mac = ':'.join(f'{b:02x}' for b in src_mac)

            # Note. Adding a VLAN tag can be as easy as
            # tagged_frame = data[0:12] + create_vlan_tag(5, 10) + data[12:]

            print(f'Destination MAC: {dest_mac}')
            print(f'Source MAC: {src_mac}')
            print(f'EtherType: {ethertype}')

            print("Received frame of size {} on interface {}".format(length, interface), flush=True)
            print("Got VLAN {} and TCI {}".format(vlan_id, vlan_tci, flush=True))

            if is_trunk(interface):
                untagged_frame = data[0:12] + data[16:]
                tagged_frame = data
            else:
                untagged_frame = data
                tagged_frame = data[0:12] + create_vlan_tag(create_ext_id(src_mac), int(VLAN_TABLE[interface])) + data[12:]

            if is_unicast(src_mac):
                CAM_TABLE[src_mac] = interface


            if dest_mac in CAM_TABLE:
                if create_ext_id(src_mac) != create_ext_id(dest_mac):
                    continue
                elif is_trunk(interface) and is_trunk(CAM_TABLE[dest_mac]):
                    send_to_link(CAM_TABLE[dest_mac], len(tagged_frame), tagged_frame)
                elif is_trunk(interface) and not is_trunk(CAM_TABLE[dest_mac]):
                    send_to_link(CAM_TABLE[dest_mac], len(untagged_frame), untagged_frame)
                elif not is_trunk(interface) and is_trunk(CAM_TABLE[dest_mac]):
                    send_to_link(CAM_TABLE[dest_mac], len(tagged_frame), tagged_frame)
                elif not is_trunk(interface) and not is_trunk(CAM_TABLE[dest_mac]):
                    send_to_link(CAM_TABLE[dest_mac], len(untagged_frame), untagged_frame)
            else:
                for i in interfaces:
                    if PORTS[i] != "b":
                        if interface != i:
                            if is_trunk(interface) and is_trunk(i):
                                send_to_link(i, len(tagged_frame), tagged_frame)
                            elif is_trunk(interface) and not is_trunk(i) and str(vlan_id) == VLAN_TABLE[i]:
                                send_to_link(i, len(untagged_frame), untagged_frame)
                            elif not is_trunk(interface) and is_trunk(i):
                                send_to_link(i, len(tagged_frame), tagged_frame)
                            elif not is_trunk(interface) and not is_trunk(i) and VLAN_TABLE[interface] == VLAN_TABLE[i]:
                                send_to_link(i, len(untagged_frame), untagged_frame)

if __name__ == "__main__":
    main()
