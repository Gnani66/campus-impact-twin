"""
Fixed-format MQTT topic builder and parser.

Topic layout, with the sensor's real UUID last:

    smart-campus
      /campus/{campus_code}
      /building/{building_code}
      /floor/{floor_code}
      /zone/{zone_code}
      /sensor/{sensor_uuid}

That is 11 segments: a prefix, then a keyword/value pair five
times. Parsing splits on "/" and compares each segment against
its expected position. Nothing here does substring matching, so
a topic cannot pass by containing the right words in the wrong
place.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.core.config import settings


# Keyword that must precede each value segment, in order.
TOPIC_KEYWORDS = (
    "campus",
    "building",
    "floor",
    "zone",
    "sensor",
)

# prefix + 5 keyword/value pairs.
SEGMENT_COUNT = 1 + (len(TOPIC_KEYWORDS) * 2)


class TopicError(ValueError):
    """
    Raised when a topic does not match the expected layout.
    """


@dataclass(frozen=True)
class ParsedTopic:
    prefix: str
    campus_code: str
    building_code: str
    floor_code: str
    zone_code: str
    sensor_id: UUID


def get_topic_prefix() -> str:
    """
    The configured prefix. Read from settings rather than
    repeated through the application.
    """

    return settings.mqtt_topic_prefix


def build_topic(
    entry: "object",
    prefix: Optional[str] = None,
) -> str:
    """
    Builds the topic for a registry entry.

    Accepts any object exposing the location attributes a
    `SensorEntry` carries, so tests do not need a registry
    instance.
    """

    resolved = prefix or get_topic_prefix()

    segments = [resolved]

    for keyword, value in (
        ("campus", entry.campus_code),
        ("building", entry.building_code),
        ("floor", entry.floor_code),
        ("zone", entry.zone_code),
        ("sensor", str(entry.sensor_id)),
    ):
        if not value:
            raise TopicError(
                f"cannot build topic: {keyword} is empty"
            )

        segments.extend((keyword, str(value)))

    return "/".join(segments)


def _parse_sensor_id(
    raw: str,
) -> UUID:
    """
    Parses the final segment strictly.

    `uuid.UUID` also accepts braces, a urn prefix and an
    unhyphenated form, so the result must round-trip to the
    same text before it is accepted.
    """

    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise TopicError(
            f"malformed sensor uuid '{raw}'"
        ) from None

    if str(parsed) != raw.lower():
        raise TopicError(
            f"sensor uuid '{raw}' is not in canonical form"
        )

    return parsed


def parse_topic(
    topic: str,
    prefix: Optional[str] = None,
) -> ParsedTopic:
    """
    Parses and fully validates a topic.

    Raises `TopicError` for a wrong prefix, a wrong segment
    count, an empty segment, a misplaced keyword or a
    malformed UUID.
    """

    resolved = prefix or get_topic_prefix()

    if not isinstance(topic, str) or not topic:
        raise TopicError("topic must be a non-empty string")

    segments = topic.split("/")

    if len(segments) != SEGMENT_COUNT:
        raise TopicError(
            f"expected {SEGMENT_COUNT} topic segments, "
            f"got {len(segments)}: '{topic}'"
        )

    if segments[0] != resolved:
        raise TopicError(
            f"unexpected topic prefix '{segments[0]}'; "
            f"expected '{resolved}'"
        )

    values = []

    for index, keyword in enumerate(TOPIC_KEYWORDS):
        keyword_index = 1 + (index * 2)
        value_index = keyword_index + 1

        found = segments[keyword_index]

        if found != keyword:
            raise TopicError(
                f"expected '{keyword}' at segment "
                f"{keyword_index}, got '{found}'"
            )

        value = segments[value_index]

        if not value.strip():
            raise TopicError(
                f"empty {keyword} segment at position "
                f"{value_index}"
            )

        values.append(value)

    campus_code, building_code, floor_code, zone_code, sensor_raw = values

    return ParsedTopic(
        prefix=resolved,
        campus_code=campus_code,
        building_code=building_code,
        floor_code=floor_code,
        zone_code=zone_code,
        sensor_id=_parse_sensor_id(sensor_raw),
    )