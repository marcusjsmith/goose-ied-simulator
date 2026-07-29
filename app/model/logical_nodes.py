"""IEC 61850 logical node definitions and dataset builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.goose.datatypes import Dbpos, GooseDataValue, Quality


@dataclass
class DataAttribute:
    da_name: str
    mms_type: str
    fc: str
    default: Any
    description: str = ""


@dataclass
class LogicalNodeTemplate:
    ln_class: str
    ln_inst: str
    description: str
    attributes: list[DataAttribute] = field(default_factory=list)

    @property
    def ln_name(self) -> str:
        return f"{self.ln_class}{self.ln_inst}"

    @property
    def ref_prefix(self) -> str:
        return f"DEMO_IED/FEEDER1/{self.ln_name}"


# Standard LN templates available for GOOSE dataset
LN_CATALOG: dict[str, LogicalNodeTemplate] = {
    "XCBR1": LogicalNodeTemplate(
        ln_class="XCBR",
        ln_inst="1",
        description="Circuit Breaker – position and health",
        attributes=[
            DataAttribute("Pos.stVal", "dbpos", "ST", Dbpos.ON, "Breaker position (1=int, 2=off, 3=on)"),
            DataAttribute("Pos.q", "quality", "ST", Quality.good(), "Position quality"),
            DataAttribute("BlkOpn.stVal", "boolean", "ST", False, "Block open command"),
            DataAttribute("BlkCls.stVal", "boolean", "ST", False, "Block close command"),
        ],
    ),
    "CSWI1": LogicalNodeTemplate(
        ln_class="CSWI",
        ln_inst="1",
        description="Switch Controller – operated switch position",
        attributes=[
            DataAttribute("Pos.stVal", "dbpos", "ST", Dbpos.ON, "Switch position"),
            DataAttribute("Pos.q", "quality", "ST", Quality.good(), "Position quality"),
        ],
    ),
    "MMXU1": LogicalNodeTemplate(
        ln_class="MMXU",
        ln_inst="1",
        description="Measurement Unit – voltages, currents, power",
        attributes=[
            DataAttribute("TotW.mag.f", "float32", "MX", 12.5, "Total active power (MW)"),
            DataAttribute("TotVAr.mag.f", "float32", "MX", 2.1, "Total reactive power (MVAr)"),
            DataAttribute("Hz.mag.f", "float32", "MX", 50.0, "Frequency (Hz)"),
            DataAttribute("PhV.phsA.cVal.mag.f", "float32", "MX", 110.0, "Phase A voltage (kV)"),
            DataAttribute("A.phsA.cVal.mag.f", "float32", "MX", 450.0, "Phase A current (A)"),
        ],
    ),
    "PTRC1": LogicalNodeTemplate(
        ln_class="PTRC",
        ln_inst="1",
        description="Protection Trip Conditioning – trip outputs",
        attributes=[
            DataAttribute("Tr.general", "boolean", "ST", False, "General trip"),
            DataAttribute("Tr.phsA", "boolean", "ST", False, "Phase A trip"),
            DataAttribute("Tr.phsB", "boolean", "ST", False, "Phase B trip"),
            DataAttribute("Tr.phsC", "boolean", "ST", False, "Phase C trip"),
            DataAttribute("Op.general", "boolean", "ST", False, "General operate"),
        ],
    ),
    "PTOC1": LogicalNodeTemplate(
        ln_class="PTOC",
        ln_inst="1",
        description="Overcurrent Protection – start and operate",
        attributes=[
            DataAttribute("Str.general", "boolean", "ST", False, "Overcurrent start"),
            DataAttribute("Op.general", "boolean", "ST", False, "Overcurrent operate"),
            DataAttribute("Str.phsA", "boolean", "ST", False, "Phase A start"),
            DataAttribute("Op.phsA", "boolean", "ST", False, "Phase A operate"),
        ],
    ),
    "PDIF1": LogicalNodeTemplate(
        ln_class="PDIF",
        ln_inst="1",
        description="Differential Protection – bus/feed differential",
        attributes=[
            DataAttribute("Str.general", "boolean", "ST", False, "Diff start"),
            DataAttribute("Op.general", "boolean", "ST", False, "Diff operate"),
            DataAttribute("Str.phsA", "boolean", "ST", False, "Phase A diff start"),
            DataAttribute("Op.phsA", "boolean", "ST", False, "Phase A diff operate"),
        ],
    ),
    "GGIO1": LogicalNodeTemplate(
        ln_class="GGIO",
        ln_inst="1",
        description="Generic I/O – alarm and indication points",
        attributes=[
            DataAttribute("Ind1.stVal", "boolean", "ST", False, "General alarm indication"),
            DataAttribute("Ind2.stVal", "boolean", "ST", False, "Fault indication"),
            DataAttribute("Ind3.stVal", "boolean", "ST", False, "Communication alarm"),
            DataAttribute("SPCSO1.stVal", "boolean", "ST", False, "Control status"),
        ],
    ),
    "RBRF1": LogicalNodeTemplate(
        ln_class="RBRF",
        ln_inst="1",
        description="Breaker Failure Protection",
        attributes=[
            DataAttribute("Str.general", "boolean", "ST", False, "Breaker failure start"),
            DataAttribute("Op.general", "boolean", "ST", False, "Breaker failure operate"),
            DataAttribute("OpEx.general", "boolean", "ST", False, "BF trip to adjacent breaker"),
        ],
    ),
    "PTEF1": LogicalNodeTemplate(
        ln_class="PTEF",
        ln_inst="1",
        description="Transient Earth Fault Protection",
        attributes=[
            DataAttribute("Str.general", "boolean", "ST", False, "Earth fault start"),
            DataAttribute("Op.general", "boolean", "ST", False, "Earth fault operate"),
        ],
    ),
}


@dataclass
class ActiveLogicalNode:
    template_key: str
    enabled_attributes: set[str] = field(default_factory=set)
    values: dict[str, Any] = field(default_factory=dict)

    def get_template(self) -> LogicalNodeTemplate:
        return LN_CATALOG[self.template_key]

    def init_defaults(self) -> None:
        template = self.get_template()
        if not self.enabled_attributes:
            self.enabled_attributes = {attr.da_name for attr in template.attributes}
        for attr in template.attributes:
            if attr.da_name not in self.values:
                self.values[attr.da_name] = attr.default

    def to_goose_values(self) -> list[GooseDataValue]:
        template = self.get_template()
        self.init_defaults()
        result: list[GooseDataValue] = []
        for attr in template.attributes:
            if attr.da_name not in self.enabled_attributes:
                continue
            result.append(
                GooseDataValue(
                    name=f"{template.ref_prefix}${attr.fc}${attr.da_name.replace('.', '$')}",
                    mms_type=attr.mms_type,
                    value=self.values.get(attr.da_name, attr.default),
                )
            )
        return result


def build_dataset(active_nodes: list[ActiveLogicalNode]) -> list[GooseDataValue]:
    dataset: list[GooseDataValue] = []
    for node in active_nodes:
        dataset.extend(node.to_goose_values())
    return dataset
