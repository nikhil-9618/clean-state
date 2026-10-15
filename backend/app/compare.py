"""Metadata comparison and sensitivity classification.

The comparison is the product's core honesty guarantee: it is computed from two
real ExifTool tag maps (before and after), so a tag is only ever reported as
"removed" if it was present before and absent after.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .exiftool import NON_METADATA_GROUPS, group_of, tag_of
from .formats import FormatSpec

Sensitivity = str  # "high" | "medium" | "low"

_HIGH_PATTERNS = (
    r"^GPS",
    r"SerialNumber$",
    r"^(Internal|Camera|Lens|Body)Serial",
    r"^(Owner|Artist|Author|Creator|LastModifiedBy|Company|Manager|Publisher)",
    r"(Email|Phone|Contact|Account|License|Address)",
    r"^(DocumentID|InstanceID|OriginalDocumentID|UUID|XMPToolkit)",
    r"^(HostComputer|DeviceManufacturer|DeviceModel|ProfileCreator|CameraOwnerName)",
    r"^(FirmwareVersion|BodyID|LensID|Software$)",
    r"^(Latitude|Longitude|Altitude|LocationInformation|Country|City|State|Sublocation)",
    r"^(SecurityClassification|Certificate|Signature)",
    r"(Copyright|Credit|Source$|SpecialInstructions)",
)

_MEDIUM_PATTERNS = (
    r"^(Make|Model|LensModel|Lens|Camera)",
    r"(Date|Time)$",
    r"^(DateTimeOriginal|CreateDate|ModifyDate|MetadataDate|DateAcquired)",
    r"^(Title|Subject|Description|Comment|UserComment|Caption|Keywords|Category|Rating)",
    r"^(Thumbnail|Preview|Image|JpgFrom|Photoshop)",
    r"^(Orientation|Software)",
    r"^(CreatorTool|Producer|RatingPercent|Instructions|Headline)",
)


@dataclass
class TagEntry:
    key: str
    group: str
    tag: str
    value: str
    sensitivity: Sensitivity = "low"

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "group": self.group,
            "tag": self.tag,
            "value": self.value,
            "sensitivity": self.sensitivity,
        }


@dataclass
class TagDiff:
    removed: list[TagEntry] = field(default_factory=list)
    added: list[TagEntry] = field(default_factory=list)
    changed: list[tuple[TagEntry, str]] = field(default_factory=list)
    retained: list[TagEntry] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "removed": [entry.as_dict() for entry in self.removed],
            "added": [entry.as_dict() for entry in self.added],
            "changed": [
                {**before.as_dict(), "value_after": after} for before, after in self.changed
            ],
            "retained": [entry.as_dict() for entry in self.retained],
            "counts": {
                "removed": len(self.removed),
                "added": len(self.added),
                "changed": len(self.changed),
                "retained": len(self.retained),
            },
            "sensitive_removed": sum(1 for e in self.removed if e.sensitivity != "low"),
            "sensitive_retained": sum(1 for e in self.retained if e.sensitivity != "low"),
        }


def classify(tag: str, group: str = "") -> Sensitivity:
    combined = f"{group}:{tag}" if group else tag
    for pattern in _HIGH_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return "high"
    for pattern in _MEDIUM_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return "medium"
    return "low"


def build_entries(tags: dict[str, str]) -> dict[str, TagEntry]:
    entries: dict[str, TagEntry] = {}
    for key, value in tags.items():
        group = group_of(key)
        if group in NON_METADATA_GROUPS:
            continue
        tag = tag_of(key)
        entries[key] = TagEntry(key=key, group=group, tag=tag, value=value, sensitivity=classify(tag, group))
    return entries


def compare(before_tags: dict[str, str], after_tags: dict[str, str]) -> TagDiff:
    before = build_entries(before_tags)
    after = build_entries(after_tags)
    diff = TagDiff()
    for key, entry in before.items():
        if key not in after:
            diff.removed.append(entry)
        elif after[key].value != entry.value:
            diff.changed.append((entry, after[key].value))
        else:
            diff.retained.append(entry)
    for key, entry in after.items():
        if key not in before:
            diff.added.append(entry)
    diff.removed.sort(key=lambda e: (e.sensitivity != "high", e.group, e.tag))
    diff.retained.sort(key=lambda e: (e.sensitivity != "high", e.group, e.tag))
    diff.changed.sort(key=lambda pair: pair[0].key)
    diff.added.sort(key=lambda e: e.key)
    return diff


def metadata_overview(tags: dict[str, str], *, limit: int = 400) -> list[dict[str, str]]:
    """All metadata tags for display, sorted by sensitivity then group."""
    entries = list(build_entries(tags).values())
    entries.sort(key=lambda e: ({"high": 0, "medium": 1, "low": 2}[e.sensitivity], e.group, e.tag))
    return [entry.as_dict() for entry in entries[:limit]]


def unverified_categories(spec: FormatSpec, findings: list[dict[str, object]]) -> list[str]:
    """Merge static per-format limits with findings from the real file."""
    categories: list[str] = []
    for item in spec.unverified:
        categories.append(item)
    for finding in findings:
        severity = str(finding.get("severity", "info"))
        category = str(finding.get("category", ""))
        detail = str(finding.get("detail", ""))
        if severity in {"notice", "warning"} and category in {
            "embedded_content",
            "revision_history",
            "trailing_data",
        }:
            categories.append(detail)
    if spec.notes:
        categories.append(spec.notes)
    return categories
