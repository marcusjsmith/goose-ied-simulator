# IEC 61850 GOOSE IED Simulator — User Guide

A Docker-based tool that simulates a substation **IED** (Intelligent Electronic Device) publishing **IEC 61850 GOOSE** multicast messages. Use the web UI to control breaker state, inject faults, and customise which logical nodes appear in the GOOSE payload — ideal for network demos, CyberVision visibility tests, and substation automation labs.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Web UI Overview](#web-ui-overview)
3. [Step-by-Step Demo Walkthrough](#step-by-step-demo-walkthrough)
4. [Fault Simulation](#fault-simulation)
5. [Managing Logical Nodes](#managing-logical-nodes)
6. [Verifying GOOSE Traffic](#verifying-goose-traffic)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)
9. [Reference](#reference)

---

## Getting Started

### Option A — Docker (recommended for live demos)

Requires a **Linux host** with Docker. Host networking is needed so GOOSE frames are sent on the correct physical interface.

```bash
cd goose-ied-simulator
docker compose up --build -d
```

Open the web UI at **http://localhost:8080** (or `http://<host-ip>:8080` from another machine on the network).

To stop:

```bash
docker compose down
```

### Option B — Local development (Mac / Windows / no multicast)

Use simulation mode to run the UI and build GOOSE frames without sending them onto the network:

```bash
cd goose-ied-simulator
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

GOOSE_SIMULATION_MODE=true uvicorn app.main:app --reload --port 8080
```

Open **http://localhost:8080**.

### Option C — Linux with real GOOSE output (no Docker)

```bash
cd goose-ied-simulator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

sudo GOOSE_INTERFACE=eth0 uvicorn app.main:app --host 0.0.0.0 --port 8080
```

> **Note:** Raw socket access requires root (`sudo`) on Linux.

---

## Web UI Overview

The UI is split into three areas:

### Header bar
| Element | Meaning |
|---------|---------|
| **Publisher Stopped / Running** | Green pulsing dot = GOOSE messages are being sent periodically |
| **Multicast MAC · APPID** | Destination address and APPID of the current GOOSE stream (e.g. `01:0C:CD:01:00:01 · APPID 0x0001`) |

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
Three panels:

1. **Fault Simulation** — inject predefined fault scenarios
2. **Logical Nodes** — add/remove LNs and toggle individual data attributes in the GOOSE payload
3. **GOOSE Statistics** — live stNum, sqNum, dataset entry count, and frame size

---

## Step-by-Step Demo Walkthrough

Follow this sequence for a typical network demo:

### 1. Start the application

```bash
docker compose up -d
```

Browse to **http://\<demo-host\>:8080**.

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
| `GOOSE_INTERFACE` | `eth0` | Network interface for GOOSE multicast egress |
| `GOOSE_APP_ID` | `0x0001` | GOOSE APPID — also determines the multicast destination MAC |
| `GOOSE_SRC_MAC` | `00:30:A7:00:01:01` | Source MAC address in GOOSE frames |
| `GOOSE_GOCB_REF` | `DEMO_IED/LLN0$GO$GcbDemo` | GOOSE Control Block reference |
| `GOOSE_DATASET` | `DEMO_IED/LLN0$dsGooseDemo` | Dataset reference string |
| `GOOSE_GO_ID` | `DEMO_IED_GOOSE` | GOOSE ID |
| `GOOSE_CONF_REV` | `1` | Configuration revision number |
| `GOOSE_TTL_MS` | `5000` | Time Allowed to Live (ms) in each GOOSE message |
| `GOOSE_MIN_INTERVAL_MS` | `100` | Retransmission interval (ms) |
| `GOOSE_SIMULATION_MODE` | `false` | `true` = build frames but do not send (for Mac/dev) |

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

### Web UI not loading

```bash
# Check the container is running
docker compose ps

# Check logs
docker compose logs -f

# Confirm port 8080 is listening
curl http://localhost:8080/api/state
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
│  · Raw Ethernet socket (AF_PACKET)                  │
│  · Multicast MAC 01:0C:CD:01:XX:YY                  │
└─────────────────────────────────────────────────────┘
```

### Network requirements

- Host network mode in Docker (frames egress the host NIC directly)
- `CAP_NET_RAW` capability for raw Ethernet sockets
- GOOSE is Layer-2 multicast — not routed unless specific substation VLAN/GMRP configuration exists
- Demo network must permit EtherType `0x88B8`

---

*Demo tool for lab and proof-of-concept use. GOOSE encoding based on IEC 61850-8-1.*
