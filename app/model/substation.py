"""Substation state model and fault simulation."""

from __future__ import annotations

import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.goose.datatypes import Dbpos, Quality
from app.model.logical_nodes import LN_CATALOG, ActiveLogicalNode, build_dataset

class BreakerState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    TRIPPING = "tripping"
    CLOSING = "closing"


class FaultType(str, Enum):
    NONE = "none"
    OVERCURRENT = "overcurrent"
    EARTH_FAULT = "earth_fault"
    BUS_DIFFERENTIAL = "bus_differential"
    BREAKER_FAILURE = "breaker_failure"
    MANUAL_TRIP = "manual_trip"


FAULT_DEFINITIONS: dict[FaultType, dict] = {
    FaultType.OVERCURRENT: {
        "name": "Phase Overcurrent",
        "description": "Simulates PTOC pickup with PTRC trip and breaker opening",
        "affected_lns": ["PTOC1", "PTRC1", "XCBR1", "MMXU1", "GGIO1"],
        "color": "#FF6B35",
    },
    FaultType.EARTH_FAULT: {
        "name": "Transient Earth Fault",
        "description": "Earth fault detected via PTEF with trip sequence",
        "affected_lns": ["PTEF1", "PTRC1", "XCBR1", "MMXU1", "GGIO1"],
        "color": "#FFB627",
    },
    FaultType.BUS_DIFFERENTIAL: {
        "name": "Bus Differential",
        "description": "Internal bus fault – PDIF operates, all connected breakers trip",
        "affected_lns": ["PDIF1", "PTRC1", "XCBR1", "MMXU1", "GGIO1"],
        "color": "#E63946",
    },
    FaultType.BREAKER_FAILURE: {
        "name": "Breaker Failure",
        "description": "Breaker fails to open – RBRF initiates backup trip",
        "affected_lns": ["RBRF1", "PTRC1", "XCBR1", "GGIO1"],
        "color": "#9D0208",
    },
    FaultType.MANUAL_TRIP: {
        "name": "Manual Trip",
        "description": "Operator-initiated trip from control centre",
        "affected_lns": ["PTRC1", "XCBR1", "GGIO1"],
        "color": "#457B9D",
    },
}


@dataclass
class SubstationState:
    breaker_state: BreakerState = BreakerState.CLOSED
    active_fault: FaultType = FaultType.NONE
    publisher_running: bool = False
    active_nodes: list[ActiveLogicalNode] = field(default_factory=list)
    goose_stats: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.active_nodes:
            self.active_nodes = self._default_nodes()

    @staticmethod
    def _default_nodes() -> list[ActiveLogicalNode]:
        defaults = ["XCBR1", "CSWI1", "MMXU1", "PTRC1", "PTOC1", "GGIO1"]
        nodes = []
        for key in defaults:
            node = ActiveLogicalNode(template_key=key)
            node.init_defaults()
            nodes.append(node)
        return nodes

    def get_node(self, key: str) -> ActiveLogicalNode | None:
        for node in self.active_nodes:
            if node.template_key == key:
                return node
        return None

    def add_logical_node(self, key: str) -> bool:
        if key not in LN_CATALOG:
            return False
        if any(n.template_key == key for n in self.active_nodes):
            return False
        node = ActiveLogicalNode(template_key=key)
        node.init_defaults()
        self.active_nodes.append(node)
        return True

    def remove_logical_node(self, key: str) -> bool:
        before = len(self.active_nodes)
        self.active_nodes = [n for n in self.active_nodes if n.template_key != key]
        return len(self.active_nodes) < before

    def set_attribute_enabled(self, ln_key: str, da_name: str, enabled: bool) -> bool:
        node = self.get_node(ln_key)
        if not node:
            return False
        if enabled:
            node.enabled_attributes.add(da_name)
        else:
            node.enabled_attributes.discard(da_name)
        return True

    def build_goose_dataset(self):
        return build_dataset(self.active_nodes)

    def update_live_measurements(self, now: float | None = None) -> None:
        """Animate MMXU1 V/I/P readings with realistic substation load variation."""
        mmxu = self.get_node("MMXU1")
        if not mmxu:
            return

        t = now if now is not None else time.time()
        s1 = math.sin(t * 0.8)
        s2 = math.sin(t * 1.4 + 1.1)
        s3 = math.sin(t * 2.3 + 0.4)

        if self.breaker_state == BreakerState.TRIPPING:
            mmxu.values["PhV.phsA.cVal.mag.f"] = round(108.0 + 3.0 * s1, 2)
            mmxu.values["A.phsA.cVal.mag.f"] = round(2800.0 + 350.0 * s2, 1)
            mmxu.values["TotW.mag.f"] = round(38.0 + 4.0 * s1, 2)
            mmxu.values["TotVAr.mag.f"] = round(8.5 + 1.2 * s2, 2)
            mmxu.values["Hz.mag.f"] = round(49.0 + 0.25 * s3, 3)
            return

        if self.breaker_state == BreakerState.OPEN:
            if self.active_fault == FaultType.EARTH_FAULT:
                mmxu.values["PhV.phsA.cVal.mag.f"] = round(85.0 + 2.0 * s1, 2)
                mmxu.values["A.phsA.cVal.mag.f"] = round(12.0 + 4.0 * abs(s2), 1)
            elif self.active_fault == FaultType.BUS_DIFFERENTIAL:
                mmxu.values["PhV.phsA.cVal.mag.f"] = round(105.0 + 4.0 * s1, 2)
                mmxu.values["A.phsA.cVal.mag.f"] = round(120.0 + 30.0 * abs(s2), 1)
            elif self.active_fault == FaultType.OVERCURRENT:
                mmxu.values["PhV.phsA.cVal.mag.f"] = round(109.5 + 0.8 * s1, 2)
                mmxu.values["A.phsA.cVal.mag.f"] = round(18.0 + 6.0 * abs(s2), 1)
            else:
                mmxu.values["PhV.phsA.cVal.mag.f"] = round(110.0 + 0.4 * s1, 2)
                mmxu.values["A.phsA.cVal.mag.f"] = round(2.0 + 1.2 * abs(s3), 1)
            mmxu.values["TotW.mag.f"] = round(max(0.0, 0.08 * abs(s2)), 3)
            mmxu.values["TotVAr.mag.f"] = round(0.12 + 0.06 * abs(s1), 2)
            mmxu.values["Hz.mag.f"] = round(50.0 + 0.015 * s3, 3)
            return

        # Breaker closed — normal loaded feeder with load fluctuation
        mmxu.values["PhV.phsA.cVal.mag.f"] = round(110.0 + 0.7 * s1 + 0.25 * s3, 2)
        mmxu.values["A.phsA.cVal.mag.f"] = round(450.0 + 28.0 * s2 + 12.0 * s1, 1)
        mmxu.values["TotW.mag.f"] = round(12.5 + 0.6 * s1 + 0.35 * s2, 2)
        mmxu.values["TotVAr.mag.f"] = round(2.1 + 0.18 * s2 + 0.08 * s3, 2)
        mmxu.values["Hz.mag.f"] = round(50.0 + 0.025 * s3, 3)

    def apply_normal_state(self) -> None:
        """Restore normal operating conditions."""
        self.active_fault = FaultType.NONE
        self.breaker_state = BreakerState.CLOSED

        xcbr = self.get_node("XCBR1")
        if xcbr:
            xcbr.values["Pos.stVal"] = Dbpos.ON
            xcbr.values["Pos.q"] = Quality.good()

        cswi = self.get_node("CSWI1")
        if cswi:
            cswi.values["Pos.stVal"] = Dbpos.ON

        mmxu = self.get_node("MMXU1")
        if mmxu:
            mmxu.values["TotW.mag.f"] = 12.5
            mmxu.values["TotVAr.mag.f"] = 2.1
            mmxu.values["Hz.mag.f"] = 50.0
            mmxu.values["PhV.phsA.cVal.mag.f"] = 110.0
            mmxu.values["A.phsA.cVal.mag.f"] = 450.0

        for ln_key in ("PTRC1", "PTOC1", "PDIF1", "PTEF1", "RBRF1"):
            node = self.get_node(ln_key)
            if node:
                for k in list(node.values.keys()):
                    if node.values[k] is True or node.values[k] is False:
                        node.values[k] = False

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind1.stVal"] = False
            ggio.values["Ind2.stVal"] = False

    def apply_fault(self, fault: FaultType) -> None:
        self.apply_normal_state()
        self.active_fault = fault

        if fault == FaultType.OVERCURRENT:
            self._apply_overcurrent()
        elif fault == FaultType.EARTH_FAULT:
            self._apply_earth_fault()
        elif fault == FaultType.BUS_DIFFERENTIAL:
            self._apply_bus_diff()
        elif fault == FaultType.BREAKER_FAILURE:
            self._apply_breaker_failure()
        elif fault == FaultType.MANUAL_TRIP:
            self._apply_manual_trip()

    def _trip_breaker(self) -> None:
        self.breaker_state = BreakerState.OPEN
        xcbr = self.get_node("XCBR1")
        if xcbr:
            xcbr.values["Pos.stVal"] = Dbpos.OFF
        cswi = self.get_node("CSWI1")
        if cswi:
            cswi.values["Pos.stVal"] = Dbpos.OFF

    def _apply_overcurrent(self) -> None:
        ptoc = self.get_node("PTOC1")
        if ptoc:
            ptoc.values["Str.general"] = True
            ptoc.values["Op.general"] = True
            ptoc.values["Str.phsA"] = True
            ptoc.values["Op.phsA"] = True

        ptrc = self.get_node("PTRC1")
        if ptrc:
            ptrc.values["Tr.general"] = True
            ptrc.values["Tr.phsA"] = True
            ptrc.values["Op.general"] = True

        mmxu = self.get_node("MMXU1")
        if mmxu:
            mmxu.values["A.phsA.cVal.mag.f"] = 3200.0
            mmxu.values["TotW.mag.f"] = 45.0
            mmxu.values["Hz.mag.f"] = 49.2

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind2.stVal"] = True

        self._trip_breaker()

    def _apply_earth_fault(self) -> None:
        ptef = self.get_node("PTEF1")
        if not ptef:
            self.add_logical_node("PTEF1")
            ptef = self.get_node("PTEF1")
        if ptef:
            ptef.values["Str.general"] = True
            ptef.values["Op.general"] = True

        ptrc = self.get_node("PTRC1")
        if ptrc:
            ptrc.values["Tr.general"] = True

        mmxu = self.get_node("MMXU1")
        if mmxu:
            mmxu.values["PhV.phsA.cVal.mag.f"] = 85.0
            mmxu.values["A.phsA.cVal.mag.f"] = 180.0

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind2.stVal"] = True

        self._trip_breaker()

    def _apply_bus_diff(self) -> None:
        pdif = self.get_node("PDIF1")
        if not pdif:
            self.add_logical_node("PDIF1")
            pdif = self.get_node("PDIF1")
        if pdif:
            pdif.values["Str.general"] = True
            pdif.values["Op.general"] = True
            pdif.values["Str.phsA"] = True
            pdif.values["Op.phsA"] = True

        ptrc = self.get_node("PTRC1")
        if ptrc:
            ptrc.values["Tr.general"] = True
            ptrc.values["Tr.phsA"] = True
            ptrc.values["Tr.phsB"] = True
            ptrc.values["Tr.phsC"] = True

        mmxu = self.get_node("MMXU1")
        if mmxu:
            mmxu.values["TotW.mag.f"] = 0.0
            mmxu.values["A.phsA.cVal.mag.f"] = 8500.0
            mmxu.values["Hz.mag.f"] = 48.5

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind1.stVal"] = True
            ggio.values["Ind2.stVal"] = True

        self._trip_breaker()

    def _apply_breaker_failure(self) -> None:
        rbrf = self.get_node("RBRF1")
        if not rbrf:
            self.add_logical_node("RBRF1")
            rbrf = self.get_node("RBRF1")
        if rbrf:
            rbrf.values["Str.general"] = True
            rbrf.values["Op.general"] = True
            rbrf.values["OpEx.general"] = True

        ptrc = self.get_node("PTRC1")
        if ptrc:
            ptrc.values["Tr.general"] = True

        xcbr = self.get_node("XCBR1")
        if xcbr:
            xcbr.values["Pos.stVal"] = Dbpos.INTERMEDIATE
            xcbr.values["Pos.q"] = Quality.questionable()

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind1.stVal"] = True
            ggio.values["Ind2.stVal"] = True

        self.breaker_state = BreakerState.TRIPPING

    def _apply_manual_trip(self) -> None:
        ptrc = self.get_node("PTRC1")
        if ptrc:
            ptrc.values["Tr.general"] = True

        ggio = self.get_node("GGIO1")
        if ggio:
            ggio.values["Ind1.stVal"] = True

        self._trip_breaker()

    def toggle_breaker(self) -> None:
        if self.breaker_state == BreakerState.CLOSED:
            self.breaker_state = BreakerState.OPEN
            xcbr = self.get_node("XCBR1")
            if xcbr:
                xcbr.values["Pos.stVal"] = Dbpos.OFF
            cswi = self.get_node("CSWI1")
            if cswi:
                cswi.values["Pos.stVal"] = Dbpos.OFF
        else:
            self.apply_normal_state()

    def to_dict(self) -> dict:
        nodes = []
        for node in self.active_nodes:
            template = node.get_template()
            nodes.append(
                {
                    "key": node.template_key,
                    "ln_name": template.ln_name,
                    "description": template.description,
                    "enabled_attributes": sorted(node.enabled_attributes),
                    "values": {
                        k: (
                            v.name
                            if isinstance(v, Dbpos)
                            else {"validity": v.validity, "detail": v.detail}
                            if isinstance(v, Quality)
                            else v
                        )
                        for k, v in node.values.items()
                    },
                    "available_attributes": [
                        {
                            "name": a.da_name,
                            "type": a.mms_type,
                            "fc": a.fc,
                            "description": a.description,
                        }
                        for a in template.attributes
                    ],
                }
            )

        return {
            "breaker_state": self.breaker_state.value,
            "active_fault": self.active_fault.value,
            "publisher_running": self.publisher_running,
            "goose_stats": self.goose_stats,
            "active_nodes": nodes,
            "available_lns": [
                {
                    "key": k,
                    "ln_name": v.ln_name,
                    "description": v.description,
                    "active": any(n.template_key == k for n in self.active_nodes),
                }
                for k, v in LN_CATALOG.items()
            ],
            "faults": [
                {
                    "type": ft.value,
                    "name": FAULT_DEFINITIONS[ft]["name"],
                    "description": FAULT_DEFINITIONS[ft]["description"],
                    "color": FAULT_DEFINITIONS[ft]["color"],
                    "affected_lns": FAULT_DEFINITIONS[ft]["affected_lns"],
                }
                for ft in FaultType
                if ft != FaultType.NONE
            ],
        }

    def snapshot(self) -> SubstationState:
        return deepcopy(self)
