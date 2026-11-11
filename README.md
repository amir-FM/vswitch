# Layer 2 Virtual Switch Implementation

## Overview
This project implements a software-based Layer 2 network switch. The system provides core switching functionalities, including dynamic MAC address learning, Virtual Local Area Network (VLAN) isolation, and loop prevention via the Spanning Tree Protocol (STP). 

## System Specifications & Features

### 1. MAC Address Learning
The Content-Addressable Memory (CAM) table is implemented as a highly efficient hashmap (dictionary) to track network topology. 

**Implementation Details:**
* The learning algorithm bypasses redundant checks by verifying the presence of a destination address directly in the CAM table, rather than first checking if the MAC is a unicast address and then searching the table.
* The system enforces strict insertion rules, ensuring that only unicast MAC addresses are recorded into the CAM table during the learning phase.

**Behavioral Example:**

![ex1](./ex1.png)

When `Host0` communicates with `Host2`:
* Frames are forwarded through the network.
* Switches avoid broadcasting every frame once the CAM tables are populated with the respective source addresses.

* **Route 1:** `H0` --- `SW0` --- `SW1` --- `H2`
* **Route 2:** `H2` --- `SW1` --- `H3`

### 2. VLAN Support (Virtual Local Area Networks)
The switch supports network segmentation through static VLAN configurations.

**Implementation Details:**
* **Configuration Parsing:** The system parses localized switch configuration files to extract the port type for each interface (Access or Trunk), storing this metadata in a dedicated list per switch.
* **Broadcast Domain Isolation:** When forwarding broadcast traffic, the system validates that the source and destination belong to the same `VLAN_ID`. 
* **Nibble Verification:** A specific nibble check is performed only if the destination address is present in the CAM table. 
* *Security Note/Optimization:* Relying on the nibble for VLAN tagging at the host level introduces a potential vulnerability, as it can be altered by the end-user. A recommended architectural optimization would be to enforce VLAN tagging strictly at the switch ingress ports, disregarding host-generated nibbles.

**Behavioral Example:**

![ex2](./ex2.png) 
![ex2_1](./ex2_1.png)

`Host0` can communicate with `Host2` but not with `Host3` due to mismatched nibble values, even though all three stations technically belong to the same VLAN. `Host0` cannot communicate with `Host1` because they reside in entirely different VLANs.

* **Route:** `H0` -*(Access)*- `SW0` -*(Trunk)*- `SW1` -*(Access)*- `H2`
* **Blocked Route:** `H0` -*(Access)*- `SW0` -*(Trunk)*- `SW1` -*(Access)*- `H3` (Nibble mismatch)
* **Blocked Route:** `H0` -*(Access)*- `SW0` -*(Access)*- `H1` (VLAN mismatch)

### 3. Spanning Tree Protocol (STP)
To prevent broadcast storms and Layer 2 loops, a simplified Spanning Tree Protocol is implemented.

**Implementation Details:**
* **Multi-threading:** The STP engine utilizes two separate threads per switch: one for transmitting HPDUs and another for PPDUs, both operating at 1-second intervals.
* **Root Bridge Election:** Upon initialization, all switches assume the role of the Root Bridge (RB) and broadcast PPDUs. If a switch receives a PPDU with a lower Root Bridge ID (RBID), it yields its root status, ceases generating its own PPDUs, and begins forwarding the superior PPDUs.
* **State Tracking:** Each interface maintains a vector storing the lowest-cost PPDU received, formatted as the tuple **`<R, c, T, p, q>`**:
  * `R` = BID of the Root Bridge that generated the message
  * `c` = Path cost from `R` to the current node
  * `T` = BID of the upstream switch that forwarded the message
  * `p` = Egress port of switch `T`
  * `q` = Ingress port on the current switch
* **Port Role Resolution:**
  * If `c` is the minimum cost path to the root $\rightarrow$ The interface becomes a **Root Port**.
  * If `T > Current Switch BID` $\rightarrow$ The interface becomes a **Designated Port**.
  * If `T < Current Switch BID` $\rightarrow$ The interface becomes a **Blocked Port**.
* **State Transition:** Upon successful role resolution, valid ports transition their internal `PORT_MODES` state from `"b"` (Blocking) to `"f"` (Forwarding
