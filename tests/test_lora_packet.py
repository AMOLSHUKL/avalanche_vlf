"""
LoRa wire-format resilience: the unpack() path must reject truncated and
corrupted radio payloads loudly, and directive-derived packets must reject
malformed zone identifiers instead of silently targeting cell (0,0).
"""
import pytest

from backend.config.loader import ConfigLoader
from backend.engine.fusion import FusionEngine
from backend.engine.geo import mission_grid_frame_from_latlon
from backend.schemas.domain import (
    TacticalDirective,
    DirectiveTypeEnum,
    PriorityZoneEnum,
)
from backend.telemetry.lora_packet import LoRaTargetPacket, LORA_PACKET_SIZE


@pytest.fixture
def grid_frame():
    return mission_grid_frame_from_latlon(34.1839, 77.5621)


def _sample_directive() -> TacticalDirective:
    return TacticalDirective(
        directive_id="DIR_TEST_01",
        target_zone_id="cell_45_35",
        directive_type=DirectiveTypeEnum.PROBE_EXCAVATE,
        priority_zone=PriorityZoneEnum.P1,
        lat=34.1843,
        lon=77.5629,
        mgrs_coord="43S GT 36343 85694",
        depth_estimate_m=1.3,
        confidence_radius_m=0.7,
        approach_azimuth_deg=135.0,
        marker_deployed=True,
        marker_frequency_mhz=866.0,
        rationale="test",
    )


def _packed_good_packet() -> bytes:
    return LoRaTargetPacket(
        msg_type=0x01, cell_x=45, cell_y=35, probability=0.5,
        depth_m=1.0, radius_m=0.5, approach_azimuth_deg=90.0,
        marker_deployed=False, respiration_locked=False, is_p1=False,
        void_detected=False, east_offset_m=100, north_offset_m=100,
    ).pack()


def test_unpack_rejects_truncated_packet():
    good = _packed_good_packet()
    assert len(good) == LORA_PACKET_SIZE == 16
    for cut in (0, 8, 14, 15):
        with pytest.raises(ValueError, match="Invalid packet size"):
            LoRaTargetPacket.unpack(good[:cut])
    with pytest.raises(ValueError, match="Invalid packet size"):
        LoRaTargetPacket.unpack(good + b"\x00")


def test_unpack_rejects_corrupt_payload_crc():
    good = bytearray(_packed_good_packet())
    good[0] ^= 0xFF  # flip payload bits; stored CRC is now stale
    with pytest.raises(ValueError, match="CRC-16"):
        LoRaTargetPacket.unpack(bytes(good))

    crc_only = bytearray(_packed_good_packet())
    crc_only[15] ^= 0xFF  # corrupt only the checksum byte
    with pytest.raises(ValueError, match="CRC-16"):
        LoRaTargetPacket.unpack(bytes(crc_only))


def test_unpack_accepts_intact_packet():
    packet = LoRaTargetPacket.unpack(_packed_good_packet())
    assert (packet.cell_x, packet.cell_y) == (45, 35)
    assert abs(packet.probability - 0.5) < 0.005


@pytest.mark.parametrize("offset", [0, 65535])
@pytest.mark.parametrize("field", ["east_offset_m", "north_offset_m"])
def test_pack_accepts_full_uint16_offset_range(grid_frame, field, offset):
    kwargs = {"east_offset_m": 100, "north_offset_m": 100}
    kwargs[field] = offset
    packet = LoRaTargetPacket(
        msg_type=0x01, cell_x=0, cell_y=0, probability=0.5,
        depth_m=1.0, radius_m=0.5, approach_azimuth_deg=90.0,
        marker_deployed=False, respiration_locked=False, is_p1=False,
        void_detected=False, **kwargs,
    )
    unpacked = LoRaTargetPacket.unpack(packet.pack())
    assert getattr(unpacked, field) == offset


@pytest.mark.parametrize("bad_zone_id", ["cell_X_9", "cell_", "", "zone_4", "cell_1_2_3"])
def test_from_directive_rejects_malformed_zone_ids(grid_frame, bad_zone_id):
    directive = _sample_directive()
    broken = directive.model_copy(update={"target_zone_id": bad_zone_id})
    with pytest.raises(ValueError, match="Malformed target_zone_id"):
        LoRaTargetPacket.from_directive(broken, grid_frame)


def test_from_directive_encodes_cell_coordinates(grid_frame):
    packet = LoRaTargetPacket.from_directive(_sample_directive(), grid_frame)
    assert (packet.cell_x, packet.cell_y) == (45, 35)
