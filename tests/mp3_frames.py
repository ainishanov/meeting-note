"""Minimal MPEG-2 Layer III frame walker for checking encoded uploads."""

from dataclasses import dataclass

MPEG2_LAYER3_SAMPLES_PER_FRAME = 576
_MPEG2_LAYER3_BITRATES_KBPS = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
_MPEG2_SAMPLE_RATES = (22050, 24000, 16000)


@dataclass(frozen=True)
class Mp3Frame:
    bitrate_kbps: int
    sample_rate: int
    mono: bool


def mp3_frame_headers(data: bytes) -> list[Mp3Frame]:
    """Return every frame header; fail if the bytes are not back-to-back frames."""
    frames = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise AssertionError(f"Truncated MP3 frame at byte {offset}")
        header = int.from_bytes(data[offset : offset + 4], "big")
        if header >> 21 != 0x7FF:
            raise AssertionError(f"No MP3 frame sync at byte {offset}")
        version = (header >> 19) & 0b11
        layer = (header >> 17) & 0b11
        if version != 0b10 or layer != 0b01:
            raise AssertionError(f"Frame at byte {offset} is not MPEG-2 Layer III")
        bitrate_kbps = _MPEG2_LAYER3_BITRATES_KBPS[(header >> 12) & 0xF]
        sample_rate = _MPEG2_SAMPLE_RATES[(header >> 10) & 0b11]
        padding = (header >> 9) & 1
        mono = (header >> 6) & 0b11 == 0b11
        frames.append(Mp3Frame(bitrate_kbps, sample_rate, mono))
        offset += 72 * bitrate_kbps * 1000 // sample_rate + padding
    return frames
