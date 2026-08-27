"""
Military-grade 16-byte packed binary C-struct serializer for LoRaWAN / MANET
NLOS mesh. Encodes high-priority target vectors, burial depth Z, approach
heading, mission-grid offsets, and a CRC-16/CCITT checksum.

Wire layout (big-endian, 16 bytes):
    1.  msg_type            uint8   0x01 = TARGET_VECTOR_LOCK
    2.  cell_x              uint8   grid column 0..255
    3.  cell_y              uint8   grid row 0..255
    4.  probability_scaled  uint8   int(P * 255)
    5.  depth_cm            uint16  burial depth, centimeters
    6.  radius_dm           uint8   confidence radius, decimeters
    7.  azimuth_deci_deg    uint16  approach bearing, tenths of a degree
    8.  flags               uint8   bit0 marker_deployed, bit1 resp_locked,
                                bit2 is_p1, bit3 void_detected
    9.  east_offset_m       uint16  meters east of the mission grid origin
    10. north_offset_m      uint16  meters north of the mission grid origin
    11. crc16_checksum      uint16  CRC-16/CCITT over bytes 0..13

Struct string: "!BBBBHBHBHHH".

Position encoding note: absolute UTM eastings (e.g. 736122 m) do not fit a
uint16, and packing them modulo 65536 is lossy and ambiguous on decode.
The wire format therefore carries meter offsets relative to the mission grid
origin (`MissionGridFrame`), which every mission participant receives in the
mission briefing and every JSON telemetry envelope. Reconstruction to an
absolute 10-digit MGRS reference is deterministic via `to_mgrs_string`.
"""
import struct
from dataclasses import dataclass

from backend.engine.geo import (
    MissionGridFrame,
    geodetic_to_utm,
)
from backend.schemas.domain import TacticalDirective

LORA_PACKET_FORMAT = "!BBBBHBHBHHH"
LORA_PACKET_SIZE = struct.calcsize(LORA_PACKET_FORMAT)  # Exact 16 Bytes
MSG_TYPE_TARGET_VECTOR = 0x01


def compute_crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: polynomial 0x1021, init 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc = (crc << 1 ^ 4129) & 65535 if crc & 32768 else crc << 1 & 65535
    return crc


@dataclass(frozen=True)
class LoRaTargetPacket:
    msg_type: int
    cell_x: int
    cell_y: int
    probability: float
    depth_m: float
    radius_m: float
    approach_azimuth_deg: float
    marker_deployed: bool
    respiration_locked: bool
    is_p1: bool
    void_detected: bool
    east_offset_m: int
    north_offset_m: int

    def pack(self) -> bytes:
        """Serialize target vector into the 16-byte packed binary payload."""
        prob_scaled = int(max(0.0, min(1.0, self.probability)) * 255.0)
        depth_cm = int(max(0.0, min(655.35, self.depth_m)) * 100.0)
        radius_dm = int(max(0.0, min(25.5, self.radius_m)) * 10.0)
        azimuth_deci = int((self.approach_azimuth_deg % 360.0) * 10.0)

        if not (0 <= self.cell_x <= 255 and 0 <= self.cell_y <= 255):
            raise ValueError(
                f"Cell indices out of uint8 range: ({self.cell_x}, {self.cell_y})"
            )
        for name, offset in (("east", self.east_offset_m), ("north", self.north_offset_m)):
            if not 0 <= offset <= 65535:
                raise ValueError(
                    f"{name} offset {offset} m outside uint16 range [0, 65535]; "
                    "target is outside the mission grid frame."
                )

        flags = 0
        if self.marker_deployed:
            flags |= 0x01
        if self.respiration_locked:
            flags |= 0x02
        if self.is_p1:
            flags |= 0x04
        if self.void_detected:
            flags |= 0x08

        payload_wo_crc = struct.pack(
            "!BBBBHBHBHH",
            self.msg_type,
            self.cell_x,
            self.cell_y,
            prob_scaled,
            depth_cm,
            radius_dm,
            azimuth_deci,
            flags,
            self.east_offset_m,
            self.north_offset_m,
        )
        crc = compute_crc16(payload_wo_crc)
        return payload_wo_crc + struct.pack("!H", crc)

    @classmethod
    def unpack(cls, raw_bytes: bytes) -> "LoRaTargetPacket":
        """Deserialize the 16-byte binary payload with CRC integrity check."""
        if len(raw_bytes) != LORA_PACKET_SIZE:
            raise ValueError(f"Invalid packet size: expected {LORA_PACKET_SIZE} bytes, got {len(raw_bytes)}")
        expected_crc = struct.unpack("!H", raw_bytes[14:16])[0]
        calculated_crc = compute_crc16(raw_bytes[:14])
        if expected_crc != calculated_crc:
            raise ValueError(f"CRC-16 verification failure: expected {expected_crc}, computed {calculated_crc}")
        msg_type, cx, cy, p_scaled, d_cm, r_dm, az_deci, flags, e_off, n_off, _ = struct.unpack(
            LORA_PACKET_FORMAT,
            raw_bytes
        )

        return cls(
            msg_type=msg_type,
            cell_x=cx,
            cell_y=cy,
            probability=round(p_scaled / 255.0, 3),
            depth_m=round(d_cm / 100.0, 2),
            radius_m=round(r_dm / 10.0, 1),
            approach_azimuth_deg=round(az_deci / 10.0, 1),
            marker_deployed=bool(flags & 0x01),
            respiration_locked=bool(flags & 0x02),
            is_p1=bool(flags & 0x04),
            void_detected=bool(flags & 0x08),
            east_offset_m=e_off,
            north_offset_m=n_off,
        )

    def to_mgrs_string(self, grid_frame: MissionGridFrame) -> str:
        """
        Reconstruct the full 10-digit MGRS reference by adding the mission
        grid origin and formatting the standard 1 m numeric suffixes.
        """
        abs_easting = grid_frame.origin_easting_m + self.east_offset_m
        abs_northing = grid_frame.origin_northing_m + self.north_offset_m
        return (
            f"{grid_frame.zone:02d}{grid_frame.band} {grid_frame.square} "
            f"{round(abs_easting) % 100000:05d} {round(abs_northing) % 100000:05d}"
        )

    @classmethod
    def from_directive(
        cls,
        directive: TacticalDirective,
        grid_frame: MissionGridFrame,
        probability: float = 0.92,
        respiration_locked: bool = False,
        void_detected: bool = False,
    ) -> "LoRaTargetPacket":
        """Construct a LoRaTargetPacket from a directive and mission georeference."""
        parts = directive.target_zone_id.replace("cell_", "").split("_")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(
                f"Malformed target_zone_id, cannot derive cell coordinates: "
                f"{directive.target_zone_id!r}"
            )
        cx, cy = int(parts[0]), int(parts[1])

        utm_origin = geodetic_to_utm(directive.lat, directive.lon)
        east_offset = round(utm_origin.easting_m - grid_frame.origin_easting_m)
        north_offset = round(utm_origin.northing_m - grid_frame.origin_northing_m)

        return cls(
            msg_type=MSG_TYPE_TARGET_VECTOR,
            cell_x=cx,
            cell_y=cy,
            probability=probability,
            depth_m=directive.depth_estimate_m,
            radius_m=directive.confidence_radius_m,
            approach_azimuth_deg=directive.approach_azimuth_deg,
            marker_deployed=directive.marker_deployed,
            respiration_locked=respiration_locked,
            is_p1=directive.priority_zone.value == "P1",
            void_detected=void_detected,
            east_offset_m=east_offset,
            north_offset_m=north_offset,
        )
