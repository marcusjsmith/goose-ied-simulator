# IEC 61850 GOOSE IED Simulator — User Guide

A Docker-based tool that simulates a substation **IED** (Intelligent Electronic Device) publishing and **subscribing to IEC 61850 GOOSE** multicast messages. Use the web UI to control breaker state, inject faults, customise logical nodes, and receive another IED’s GOOSE stream — including two containers that subscribe to each other, on a laptop or a Raspberry Pi.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Two IEDs subscribing to each other](#two-ieds-subscribing-to-each-other)
3. [Raspberry Pi](#raspberry-pi) — including [two IEDs on two Raspberry Pis](#scenario--two-ieds-on-two-raspberry-pis)
4. [Web UI Overview](#web-ui-overview)
5. [Step-by-Step Demo Walkthrough](#step-by-step-demo-walkthrough)
6. [Fault Simulation](#fault-simulation)
7. [Managing Logical Nodes](#managing-logical-nodes)
8. [Verifying GOOSE Traffic](#verifying-goose-traffic)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Reference](#reference)

---

## Getting Started

### Option A — Single container (Mac / Windows / Linux)

Default compose maps the UI to **port 8082** and uses a UDP GOOSE overlay so subscribe works without raw Ethernet.

```bash
cd goose-ied-simulator
docker compose up --build -d
```

Open **http://localhost:8082**.

To stop:

```bash
docker compose down
```

### Option B — Two IEDs that subscribe to each other

```bash
docker compose -f docker-compose.pair.yml up --build -d
```

| IED | UI | Publishes APPID | Subscribes to |
|-----|----|-----------------|---------------|
| IED_A | http://localhost:8082 | `0x0001` | `0x0002` |
| IED_B | http://localhost:8083 | `0x0002` | `0x0001` |

On each UI click **Start GOOSE**. The other IED’s **Received** tab should fill with decoded frames. See [Two IEDs subscribing to each other](#two-ieds-subscribing-to-each-other).

### Option C — Local development (no Docker)

```bash
cd goose-ied-simulator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

GOOSE_SIMULATION_MODE=true GOOSE_TRANSPORT=udp uvicorn app.main:app --reload --port 8080
```

Open **http://localhost:8080**.

### Option D — Linux / Raspberry Pi with real L2 GOOSE

Raw Ethernet (`EtherType 0x88B8`) needs host networking and `CAP_NET_RAW`. See [Raspberry Pi](#raspberry-pi).

```bash
sudo GOOSE_INTERFACE=eth0 GOOSE_SIMULATION_MODE=false GOOSE_TRANSPORT=raw \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

---

## Two IEDs subscribing to each other

Each instance publishes on its own **APPID / multicast MAC** and listens for the peer APPID. Own frames are ignored (matched on source MAC and GoCB).

**Transports**

| Mode | Where it works | What is sent |
|------|----------------|--------------|
| `udp` | Docker Desktop (Mac/Windows), Linux bridge | Full GOOSE Ethernet frame as UDP multicast `239.118.50.1:61850` |
| `raw` | Linux / Raspberry Pi host network | Real IEC 61850 L2 GOOSE (`01:0C:CD:01:XX:YY`, EtherType `0x88B8`) |
| `both` | Linux when you want L2 plus the UDP overlay | Both of the above |

Pair compose uses `udp` so two containers on one laptop can hear each other without a substation switch.

1. Start the pair: `docker compose -f docker-compose.pair.yml up --build -d`
2. Open IED_A (`:8082`) and IED_B (`:8083`)
3. Click **Start GOOSE** on both
4. Open the **Received** tab — you should see the peer `goID`, `stNum`, and dataset
5. Toggle a breaker on IED_A — IED_B should show a **STATE CHANGE** (`sqNum` back to 0)

---

## Raspberry Pi

The image is `linux/arm64` compatible (`python:3.12-slim-bookworm`). Use **Raspberry Pi OS 64-bit** (Bookworm or later) with Docker.

GOOSE is Layer-2 multicast. Two Pis only hear each other if they sit on the **same Ethernet VLAN / broadcast domain** — not across a router, NAT, or Wi‑Fi client isolation.

### What you need

| Item | Notes |
|------|--------|
| Two Raspberry Pis | Pi 4 or Pi 5 recommended, 64-bit OS |
| Wired Ethernet | Use the RJ45 port, not Wi‑Fi. GOOSE multicast over WLAN is unreliable |
| Same L2 network | Same switch (or same VLAN). No routing between the boxes |
| This repository | Clone or copy `goose-ied-simulator` onto **both** Pis |

### Prepare each Pi (do this on Pi 1 and Pi 2)

```bash
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# Log out and back in (or reboot) so the docker group applies

git clone https://github.com/marcusjsmith/goose-ied-simulator.git
cd goose-ied-simulator

# Confirm the wired interface name (Pi 5 is often eth0 or end0)
ip -br link
```

If the NIC is `end0` instead of `eth0`, pass `GOOSE_INTERFACE=end0` in the commands below.

Optional: disable Wi‑Fi for the demo so all traffic uses Ethernet:

```bash
sudo rfkill block wifi
```

### Scenario — two IEDs on two Raspberry Pis

This is the usual lab layout: **Pi 1 = IED_A** (publisher APPID `0x0001`) and **Pi 2 = IED_B** (publisher APPID `0x0002`). Each box runs **one** container with host networking so GOOSE frames leave the Pi’s Ethernet port as real IEC 61850 L2 multicast (`EtherType 0x88B8`).

```
  Pi 1 (IED_A)                         Pi 2 (IED_B)
  APPID 0x0001  ──GOOSE──►  switch  ◄──GOOSE──  APPID 0x0002
  listens 0x0002           same VLAN            listens 0x0001
  UI :8080                                      UI :8080
```

| | Pi 1 — IED_A | Pi 2 — IED_B |
|--|--------------|--------------|
| Compose service | `ied-a` | `ied-b` |
| IED name | `IED_A` | `IED_B` |
| Publishes APPID | `0x0001` | `0x0002` |
| Destination MAC | `01:0C:CD:01:00:01` | `01:0C:CD:01:00:02` |
| Source MAC | `00:30:A7:00:01:01` | `00:30:A7:00:01:02` |
| Subscribes to | `0x0002` | `0x0001` |
| Web UI | `http://<pi-1-ip>:8080` | `http://<pi-2-ip>:8080` |
| Transport | `raw` (real L2 GOOSE) | `raw` |

`docker-compose.pi.yml` already encodes this pairing. You only start **one** service per Pi.

**Pi 1 — deploy IED_A**

```bash
cd goose-ied-simulator
GOOSE_INTERFACE=eth0 docker compose -f docker-compose.pi.yml up --build -d ied-a
docker compose -f docker-compose.pi.yml ps
```

**Pi 2 — deploy IED_B**

```bash
cd goose-ied-simulator
GOOSE_INTERFACE=eth0 docker compose -f docker-compose.pi.yml up --build -d ied-b
docker compose -f docker-compose.pi.yml ps
```

Both UIs listen on host port **8080** because each Pi has its own network stack. Find the addresses with `hostname -I` (or your DHCP reservations).

**Configure from the UI (same on both boxes)**

1. Open Pi 1 at `http://<pi-1-ip>:8080` and Pi 2 at `http://<pi-2-ip>:8080`
2. Confirm the header shows **IED_A** / APPID `0x0001` on Pi 1 and **IED_B** / APPID `0x0002` on Pi 2
3. On each sidebar **GOOSE Subscriber** panel, confirm the peer APPID (`0x0002` on IED_A, `0x0001` on IED_B). The subscriber auto-starts; use **Start Subscribe** if the pill still says Idle
4. Click **Start GOOSE** on **both** UIs
5. Open the **Received** tab on each Pi — you should see the other IED’s `goID` (`IED_A_GOOSE` / `IED_B_GOOSE`), `stNum`, and dataset
6. Toggle the breaker on Pi 1 — Pi 2 should show a **STATE CHANGE** (`sqNum` returns to 0)

**Verify on the wire (from either Pi)**

```bash
# All GOOSE on the LAN
sudo tcpdump -i eth0 -nn ether proto 0x88b8

# Frames from IED_A
sudo tcpdump -i eth0 -nn ether dst 01:0c:cd:01:00:01

# Frames from IED_B
sudo tcpdump -i eth0 -nn ether dst 01:0c:cd:01:00:02
```

You should see both destination MACs while both publishers are running.

**Change the interface or APPID pairing**

Create a `.env` next to the compose file on that Pi (do **not** use the same APPID on both boxes):

```env
# Example on Pi 1 if the NIC is end0
GOOSE_INTERFACE=end0
```

Then recreate:

```bash
docker compose -f docker-compose.pi.yml up -d ied-a
```

To subscribe to a non-default peer APPID, set it in the **GOOSE Subscriber** panel and click **Start Subscribe**, or set `GOOSE_SUBSCRIBE_APP_ID` in the environment for that service.

**Stop / update**

```bash
docker compose -f docker-compose.pi.yml down
# After a git pull
GOOSE_INTERFACE=eth0 docker compose -f docker-compose.pi.yml up --build -d ied-a   # or ied-b
```

**Two-Pi checklist if Received stays empty**

- Both publishers are running (green **Publisher Running** pills)
- Subscriber pills show **Listening**, peer APPIDs are swapped (`0x0001` ↔ `0x0002`)
- Cables are in the **Ethernet** ports, same switch/VLAN, no router between them
- `GOOSE_INTERFACE` matches `ip -br link` (`eth0` vs `end0`)
- Managed switch is not filtering unknown multicast or EtherType `0x88B8` (disable IGMP snooping for the demo VLAN if needed)
- `tcpdump` on each Pi sees the **other** destination MAC, not only its own

### Two IEDs on one Pi (host network, real GOOSE)

Use this only when both containers share a single Pi’s NIC. UIs are on different ports because they share one host network namespace.

```bash
GOOSE_INTERFACE=eth0 docker compose -f docker-compose.pi.yml up --build -d
```

- IED_A UI: `http://<pi-ip>:8080` (APPID `0x0001`, subscribes to `0x0002`)
- IED_B UI: `http://<pi-ip>:8081` (APPID `0x0002`, subscribes to `0x0001`)

A packet capture on the same VLAN will show EtherType `0x88b8` for both APPIDs.

---

## Web UI Overview

The UI is split into three areas:

### Header bar
| Element | Meaning |
|---------|---------|
| **Publisher Stopped / Running** | Green pulsing dot = GOOSE messages are being sent periodically |
| **Subscriber Idle / Listening** | Green pulsing dot = this IED is listening for a peer APPID |
| **Multicast MAC · APPID** | Destination address and APPID of **this** IED’s published stream |

### Single-Line Diagram (main panel)
An SVG diagram of a 110 kV feeder showing:

- **110 kV Bus Bar** — top horizontal bus
- **DS1 (CSWI1)** — disconnector / switch
- **CB1 (XCBR1)** — circuit breaker (green = closed, red = open, amber flashing = tripping)
- **CT / VT** — instrument transformers
- **LOAD** — load connection with live power reading
- **DEMO_IED** — protection IED box showing V, I, P, f readings and a status LED
- **GOOSE Multicast arrow** — shows the GOOSE path from IED to the network

Below the diagram are four control buttons:

| Button | Action |
|--------|--------|
| **Toggle Breaker** | Manually open or close CB1 |
| **Start GOOSE** | Begin periodic GOOSE multicast publishing |
| **Stop GOOSE** | Stop publishing |
| **Publish Now** | Send one immediate GOOSE message (increments `stNum`) |

### Right sidebar
Four panels:

1. **GOOSE Subscriber** — peer APPID, start/stop listen, last received goID / stNum / sqNum
2. **Fault Simulation** — inject predefined fault scenarios
3. **Logical Nodes** — add/remove LNs and toggle individual data attributes in the GOOSE payload
4. **GOOSE Statistics** — live stNum, sqNum, dataset entry count, and frame size

---

## Step-by-Step Demo Walkthrough

Follow this sequence for a typical network demo:

### 1. Start the application

```bash
docker compose up -d
```

Browse to **http://\<demo-host\>:8082**.

### 2. Start GOOSE publishing

Click **Start GOOSE** in the diagram panel.

- The header status changes to **Publisher Running** (green dot)
- GOOSE Statistics begin updating (stNum, sqNum incrementing)
- Frames are sent every 100 ms to multicast MAC `01:0C:CD:01:00:01`

### 3. Confirm traffic on the network

On a machine connected to the same L2 segment (see [Verifying GOOSE Traffic](#verifying-goose-traffic)):

```bash
sudo tcpdump -i eth0 -nn ether dst 01:0c:cd:01:00:01
```

You should see repeating GOOSE frames with EtherType `0x88b8`.

### 4. Inject a fault

In the **Fault Simulation** panel, click **Phase Overcurrent**.

Observe on the diagram:
- Breaker CB1 turns **red** (open)
- Disconnector blade rotates to open position
- IED LED turns **red**
- Fault overlay appears on the diagram
- IED readings change (current jumps to 3200 A, frequency drops)
- GOOSE `stNum` increments (state change message sent)

### 5. Show GOOSE payload change

Expand **PTOC1** and **PTRC1** in the Logical Nodes panel — you'll see `Op.general` and `Tr.general` set to **TRUE**.

### 6. Clear the fault

Click **Clear Fault / Restore Normal**.

- Breaker closes, readings return to normal
- Protection flags reset to false
- Another GOOSE state-change message is published

### 7. Customise the GOOSE dataset (optional)

Use the Logical Nodes panel to:
- Add **PDIF1** or **RBRF1** from the dropdown
- Uncheck individual attributes you don't want in the payload
- Click **Publish Now** to send the updated dataset immediately

### 8. Stop publishing

Click **Stop GOOSE** when the demo is complete.

---

## Fault Simulation

Each fault button simulates a realistic protection sequence and automatically adds any missing logical nodes to the GOOSE dataset.

| Fault | What happens | Logical nodes activated |
|-------|-------------|------------------------|
| **Phase Overcurrent** | Overcurrent pickup, trip issued, breaker opens. Current rises to 3200 A. | PTOC1 → PTRC1 → XCBR1, GGIO1 |
| **Transient Earth Fault** | Earth fault detected, voltage drops to 85 kV, breaker trips. PTEF1 is auto-added if not present. | PTEF1 → PTRC1 → XCBR1, GGIO1 |
| **Bus Differential** | Internal bus fault, differential operate, all phases trip, high fault current (8500 A). PDIF1 auto-added. | PDIF1 → PTRC1 → XCBR1, GGIO1 |
| **Breaker Failure** | Breaker stuck in intermediate position, failure relay operates, alarms raised. RBRF1 auto-added. | RBRF1 → PTRC1, XCBR1 (intermediate), GGIO1 |
| **Manual Trip** | Operator-initiated trip from control centre, breaker opens. | PTRC1 → XCBR1, GGIO1 |

Click **Clear Fault / Restore Normal** at any time to reset all protection flags, close the breaker, and restore measurement values to their normal state.

---

## Managing Logical Nodes

The GOOSE message payload is built from the logical nodes (LNs) you have active. Each LN contributes one or more data attributes.

### Add a logical node

1. Select an LN from the dropdown in the **Logical Nodes** panel (e.g. `PDIF1 – Differential Protection`)
2. Click **+ Add**
3. The LN appears in the list and its attributes are included in the next GOOSE message
4. A state-change GOOSE message is sent automatically (`stNum` increments)

### Remove a logical node

Click the **×** button on the LN card header. The LN is removed from the GOOSE dataset.

### Toggle individual attributes

1. Click an LN card header to expand it
2. Check or uncheck individual data attributes (e.g. `Pos.stVal`, `Tr.general`)
3. Checked attributes are included in the GOOSE payload; unchecked ones are excluded
4. Changes trigger an immediate state-change GOOSE message

### Default logical nodes

These are included when the app first starts:

| LN | Role |
|----|------|
| XCBR1 | Circuit breaker position |
| CSWI1 | Disconnector position |
| MMXU1 | Measurements (P, Q, Hz, V, I) |
| PTRC1 | Trip conditioning outputs |
| PTOC1 | Overcurrent protection |
| GGIO1 | Alarm / indication points |

### Available to add

| LN | Role |
|----|------|
| PDIF1 | Bus/feeder differential protection |
| RBRF1 | Breaker failure protection |
| PTEF1 | Transient earth fault protection |

---

## Verifying GOOSE Traffic

### tcpdump (any Linux host on the same L2 network)

```bash
# All GOOSE frames (EtherType 0x88b8)
sudo tcpdump -i eth0 -nn ether proto 0x88b8

# Filter by multicast MAC for default APPID 0x0001
sudo tcpdump -i eth0 -nn ether dst 01:0c:cd:01:00:01

# Verbose — show frame length
sudo tcpdump -i eth0 -nn -v ether dst 01:0c:cd:01:00:01
```

### Wireshark

1. Capture on the demo interface
2. Apply display filter: `eth.type == 0x88b8`
3. Expand the GOOSE protocol tree to inspect gocbRef, stNum, sqNum, and dataset entries

### Expected frame details (defaults)

| Field | Value |
|-------|-------|
| Destination MAC | `01:0C:CD:01:00:01` |
| Source MAC | `00:30:A7:00:01:01` |
| EtherType | `0x88B8` |
| APPID | `0x0001` |
| GOOSE Control Block | `DEMO_IED/LLN0$GO$GcbDemo` |
| Dataset | `DEMO_IED/LLN0$dsGooseDemo` |
| GOID | `DEMO_IED_GOOSE` |
| Publish interval | 100 ms (retransmissions), immediate on state change |

---

## Configuration

Set environment variables in `docker-compose.yml` or a `.env` file in the project root.

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOSE_IED_NAME` | `DEMO_IED` | Display name on the SLD and default GoCB/dataset prefix |
| `GOOSE_INTERFACE` | `eth0` | Network interface for raw GOOSE (Linux/Pi) |
| `GOOSE_APP_ID` | `0x0001` | GOOSE APPID — also determines the multicast destination MAC |
| `GOOSE_SRC_MAC` | `00:30:A7:00:01:01` | Source MAC address in GOOSE frames |
| `GOOSE_GOCB_REF` | `{IED}/LLN0$GO$GcbDemo` | GOOSE Control Block reference |
| `GOOSE_DATASET` | `{IED}/LLN0$dsGooseDemo` | Dataset reference string |
| `GOOSE_GO_ID` | `{IED}_GOOSE` | GOOSE ID |
| `GOOSE_CONF_REV` | `1` | Configuration revision number |
| `GOOSE_TTL_MS` | `5000` | Time Allowed to Live (ms) in each GOOSE message |
| `GOOSE_MIN_INTERVAL_MS` | `100` | Retransmission interval (ms) |
| `GOOSE_SIMULATION_MODE` | `false` | `true` = do not open a raw Ethernet socket |
| `GOOSE_TRANSPORT` | `udp` if simulation, else `both` | `udp`, `raw`, or `both` |
| `GOOSE_UDP_GROUP` | `239.118.50.1` | UDP overlay multicast group |
| `GOOSE_UDP_PORT` | `61850` | UDP overlay port |
| `GOOSE_SUBSCRIBE_APP_ID` | peer of own APPID | APPID this IED listens for |
| `GOOSE_SUBSCRIBE_AUTO_START` | `true` | Start the subscriber when the process boots |
| `GOOSE_HTTP_PORT` | `8080` | HTTP port (used with host networking on Pi) |

**Multicast MAC formula:** `01:0C:CD:01:XX:YY` where `XX:YY` = APPID in hex.  
Example: APPID `0x0001` → MAC `01:0C:CD:01:00:01`.

### Example — change interface and APPID

Create a `.env` file:

```env
GOOSE_INTERFACE=enp0s3
GOOSE_APP_ID=0x0100
```

Then restart:

```bash
docker compose down && docker compose up -d
```

The new multicast MAC will be `01:0C:CD:01:01:00`.

---

## Troubleshooting

### Publisher shows "Running" but no frames on the network

- Confirm the container is using **host network mode** (`network_mode: host` in docker-compose.yml)
- Check `GOOSE_INTERFACE` matches the actual interface name: `ip link show`
- On Docker Desktop for Mac/Windows, host networking is not fully supported — deploy on a Linux VM or bare-metal host for real multicast
- Verify with `GOOSE_SIMULATION_MODE=false` (the default in Docker)

### "Permission denied" or socket errors on Linux

Raw Ethernet sockets require elevated privileges:

```bash
sudo GOOSE_INTERFACE=eth0 uvicorn app.main:app --host 0.0.0.0 --port 8080
```

In Docker, `CAP_NET_RAW` and `CAP_NET_ADMIN` are already granted via docker-compose.yml.

### Received tab stays empty

- Click **Start GOOSE** on the *peer* IED — subscribe only shows frames that arrive on the network
- Confirm peer APPID in the Subscriber panel matches the other IED’s published APPID (`0x0001` ↔ `0x0002` in the pair compose file)
- For laptop/Docker Desktop, use `docker-compose.pair.yml` (`GOOSE_TRANSPORT=udp`) so both containers share the `goose-lan` bridge
- For Raspberry Pi / Linux L2 GOOSE, both hosts must be on the same VLAN; confirm with `sudo tcpdump -i eth0 ether proto 0x88b8`
- Own frames are ignored — a single IED will not appear in its own Received tab

### Web UI not loading

```bash
# Check the container is running
docker compose ps

# Check logs
docker compose logs -f

# Confirm the mapped port is listening (8082 in the default compose file)
curl http://localhost:8082/api/state
```

### Fault button clicked but breaker didn't change

- Ensure the page has loaded fully (WebSocket connected — status pills are populated)
- Check browser console for errors
- Verify via API: `curl http://localhost:8080/api/state | python3 -m json.tool`

### GOOSE frames visible in tcpdump but not in CyberVision / monitoring tool

- GOOSE is Layer-2 only — the monitoring device must be on the same VLAN/broadcast domain
- Confirm EtherType `0x88B8` is not blocked by switch ACLs
- Some tools filter by APPID or GOID — check they match the configured values above

---

## Reference

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/state` | Full substation and GOOSE state |
| POST | `/api/publisher/start` | Start GOOSE publishing |
| POST | `/api/publisher/stop` | Stop GOOSE publishing |
| POST | `/api/publisher/publish` | Send one state-change message |
| POST | `/api/subscriber/start` | `{"app_id":"0x0002"}` — listen for a peer stream |
| POST | `/api/subscriber/stop` | Stop listening |
| POST | `/api/goose/subscribe/messages/clear` | Clear received-message log |
| POST | `/api/breaker/toggle` | Open/close breaker |
| POST | `/api/fault/apply` | `{"fault_type": "overcurrent"}` |
| POST | `/api/fault/clear` | Restore normal state |
| POST | `/api/logical-nodes/add` | `{"ln_key": "PDIF1"}` |
| POST | `/api/logical-nodes/remove` | `{"ln_key": "PDIF1"}` |
| POST | `/api/logical-nodes/attribute` | `{"ln_key":"XCBR1","da_name":"Pos.stVal","enabled":true}` |
| WS | `/ws` | Real-time state push (WebSocket) |

Fault types for `/api/fault/apply`: `overcurrent`, `earth_fault`, `bus_differential`, `breaker_failure`, `manual_trip`.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  Web UI (SVG SLD + Controls)                        │
│  WebSocket / REST API                               │
├─────────────────────────────────────────────────────┤
│  Substation State Model                             │
│  · Breaker / measurements / fault engine            │
│  · Active logical nodes → GOOSE dataset builder     │
├─────────────────────────────────────────────────────┤
│  GOOSE Publisher (Python)                           │
│  · ASN.1 BER encoder (IEC 61850-8-1)                │
│  · Raw Ethernet socket (AF_PACKET) and/or UDP       │
│  · Multicast MAC 01:0C:CD:01:XX:YY                  │
├─────────────────────────────────────────────────────┤
│  GOOSE Subscriber                                   │
│  · Raw / UDP listen, BER decoder                    │
│  · Filters by peer APPID, ignores own GoCB/MAC      │
└─────────────────────────────────────────────────────┘
```

### Network requirements

- Host network mode in Docker (frames egress the host NIC directly)
- `CAP_NET_RAW` capability for raw Ethernet sockets
- GOOSE is Layer-2 multicast — not routed unless specific substation VLAN/GMRP configuration exists
- Demo network must permit EtherType `0x88B8`

---

*Demo tool for lab and proof-of-concept use. GOOSE encoding based on IEC 61850-8-1.*
