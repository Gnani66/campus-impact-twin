"""
Topic builder and parser tests.
"""

from uuid import UUID

import pytest

from app.telemetry.topics import (
    SEGMENT_COUNT,
    TopicError,
    build_topic,
    get_topic_prefix,
    parse_topic,
)


from conftest import SEED_IDS


PREFIX = "smart-campus"

VALID_TOPIC = (
    f"{PREFIX}/campus/CIT-MAIN"
    "/building/ACADEMIC-BLK-A"
    "/floor/A-F1"
    "/zone/LH01"
    f"/sensor/{SEED_IDS['TEMP-LH01']}"
)


def test_configured_prefix_comes_from_settings():
    assert get_topic_prefix() == PREFIX


def test_build_topic_from_registry_entry(
    temperature_entry,
):
    topic = build_topic(temperature_entry)

    assert topic == VALID_TOPIC
    assert len(topic.split("/")) == SEGMENT_COUNT


def test_build_topic_honours_explicit_prefix(
    temperature_entry,
):
    topic = build_topic(
        temperature_entry, prefix="staging-campus"
    )

    assert topic.startswith("staging-campus/campus/")
    assert topic.endswith(str(temperature_entry.sensor_id))


def test_build_topic_carries_energy_sensor_uuid(
    energy_entry,
):
    topic = build_topic(energy_entry)

    assert topic.endswith(SEED_IDS["ENERGY-LH01"])


def test_parse_topic_round_trip(temperature_entry):
    parsed = parse_topic(build_topic(temperature_entry))

    assert parsed.prefix == PREFIX
    assert parsed.campus_code == "CIT-MAIN"
    assert parsed.building_code == "ACADEMIC-BLK-A"
    assert parsed.floor_code == "A-F1"
    assert parsed.zone_code == "LH01"
    assert str(parsed.sensor_id) == (
        SEED_IDS["TEMP-LH01"]
    )


def test_parse_topic_is_not_substring_matching():
    """
    Right words in the wrong order must not parse.
    """

    scrambled = VALID_TOPIC.replace(
        "/zone/LH01", "/floor/LH01"
    )

    with pytest.raises(TopicError):
        parse_topic(scrambled)


@pytest.mark.parametrize(
    "topic,fragment",
    [
        (
            VALID_TOPIC.replace(PREFIX, "other-campus"),
            "unexpected topic prefix",
        ),
        (VALID_TOPIC.replace("/sensor/", "/device/"),
         "expected 'sensor'"),
        (VALID_TOPIC + "/extra", "topic segments"),
        ("/".join(VALID_TOPIC.split("/")[:-1]),
         "topic segments"),
        (VALID_TOPIC.replace("/zone/LH01", "/zone/"),
         "empty zone segment"),
        (VALID_TOPIC.replace("/floor/A-F1", "/floor/  "),
         "empty floor segment"),
        (VALID_TOPIC.replace(
            SEED_IDS["TEMP-LH01"], "1234"
        ), "malformed sensor uuid"),
        (VALID_TOPIC.replace(
            SEED_IDS["TEMP-LH01"], "not-a-uuid"
        ), "malformed sensor uuid"),
        (VALID_TOPIC.replace(
            SEED_IDS["TEMP-LH01"],
            SEED_IDS["TEMP-LH01"].replace("-", ""),
        ), "canonical form"),
        ("", "non-empty string"),
        ("smart-campus", "topic segments"),
    ],
)
def test_malformed_topics_are_rejected(topic, fragment):
    with pytest.raises(TopicError) as excinfo:
        parse_topic(topic)

    assert fragment in str(excinfo.value)


def test_parse_topic_rejects_non_string():
    with pytest.raises(TopicError):
        parse_topic(None)


def test_parse_topic_rejects_wrong_prefix_explicitly(
    temperature_entry,
):
    topic = build_topic(
        temperature_entry, prefix="staging-campus"
    )

    with pytest.raises(TopicError) as excinfo:
        parse_topic(topic)

    assert "unexpected topic prefix" in str(excinfo.value)


def test_parsed_sensor_id_is_a_uuid(temperature_entry):
    parsed = parse_topic(build_topic(temperature_entry))

    assert isinstance(parsed.sensor_id, UUID)
    assert parsed.sensor_id == temperature_entry.sensor_id


def test_build_topic_rejects_empty_location_code(
    temperature_entry,
):
    """
    A registry entry without a zone code cannot produce a
    valid topic.
    """

    from dataclasses import replace

    broken = replace(
        temperature_entry, zone_code=""
    )

    with pytest.raises(TopicError):
        build_topic(broken)


def test_zone_code_from_topic_is_not_used_for_lookup(
    temperature_entry,
):
    """
    Parsing is structural: it yields a zone code string and a
    UUID. Resolving those to registry entries is a separate
    step, so a fabricated topic parses but does not resolve.
    """

    fabricated = (
        f"{PREFIX}/campus/CIT-MAIN"
        "/building/ACADEMIC-BLK-A"
        "/floor/A-F1"
        "/zone/ZZ99"
        f"/sensor/{SEED_IDS['TEMP-LH01']}"
    )

    parsed = parse_topic(fabricated)

    assert parsed.zone_code == "ZZ99"
    assert str(parsed.sensor_id) == (
        SEED_IDS["TEMP-LH01"]
    )