"""
Tests for the vision service: temporal smoothing and video.

Smoothing is the reason this module exists. A detector that
reports 47 people and then 0 for the next frame has not observed
an empty room; it has missed a detection. These tests pin the
behaviour that keeps one bad frame from becoming a reported
occupancy change.

Video handling is exercised against a file this module builds
itself, so the tests need no fixture image and no checked-in
binary. Where a test cannot run because OpenCV is absent it
skips rather than fails: smoothing must stay testable on a
machine set up only for the detector.
"""

from pathlib import Path

import pytest


def _opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False

    return True


requires_opencv = pytest.mark.skipif(
    not _opencv_available(),
    reason=(
        "opencv-python is not installed; video tests skip"
    ),
)


class StubDetector:
    """
    Returns a scripted sequence of counts.

    Mirrors only the part of `PersonDetector.detect` the service
    uses, so smoothing can be tested without a model.
    """

    def __init__(self, counts):
        self.counts = list(counts)
        self.calls = 0

    def detect(self, data, declared_content_type=None):
        count = self.counts[
            min(self.calls, len(self.counts) - 1)
        ]

        self.calls += 1

        class Result:
            pass

        result = Result()
        result.people_count = count
        result.confidence = 0.9

        return result


# ============================================================
# SMOOTHING
# ============================================================


class TestSmoothing:
    def test_spec_example_smooths_to_46(self):
        """
        The worked example from the specification: frames of
        47, 45, 46, 46 and 47 describe one steady room holding
        about 46 people.
        """

        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([47, 45, 46, 46, 47])
        )

        for _ in range(5):
            result = service.process_frame(b"frame")

        assert result.raw_count == 47
        assert result.smoothed_count == 46

    def test_single_outlier_does_not_move_the_count(self):
        """
        A missed detection must not drag the reported figure.
        The mean of [47, 45, 46, 46, 0] is 36.8, which describes
        no moment that occurred; the median is 46.
        """

        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([47, 45, 46, 46, 0])
        )

        for _ in range(5):
            result = service.process_frame(b"frame")

        assert result.raw_count == 0
        assert result.smoothed_count == 46

    def test_single_phantom_does_not_move_the_count(self):
        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46, 46, 46, 46, 99])
        )

        for _ in range(5):
            result = service.process_frame(b"frame")

        assert result.smoothed_count == 46

    def test_real_change_still_shows_up(self):
        """
        Smoothing must dampen noise, not hide a genuine change.
        After five frames of a steady room, a sustained new
        count has to move the reported figure.
        """

        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46, 46, 46, 46, 46, 20])
        )

        for _ in range(6):
            result = service.process_frame(b"frame")

        assert result.smoothed_count == 46

        for _ in range(4):
            result = service.process_frame(b"frame")

        assert result.smoothed_count == 20

    def test_window_is_bounded(self):
        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([1]),
            window_size=3,
        )

        for _ in range(10):
            result = service.process_frame(b"frame")

        assert len(result.window) == 3

    def test_warmed_up_only_once_window_is_full(self):
        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46]),
            window_size=3,
        )

        states = [
            service.process_frame(b"frame").warmed_up
            for _ in range(4)
        ]

        assert states == [False, False, True, True]

    def test_first_frame_is_still_usable(self):
        """
        A single frame has nothing to smooth, but refusing to
        answer would mean no reading at all until the window
        filled. It reports the frame's own count and says it is
        not warmed up.
        """

        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46])
        )

        result = service.process_frame(b"frame")

        assert result.smoothed_count == 46
        assert result.warmed_up is False

    def test_reset_clears_the_window(self):
        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46, 46, 46, 46, 46])
        )

        for _ in range(5):
            service.process_frame(b"frame")

        service.reset()

        result = service.process_frame(b"frame")

        assert result.window == [46]
        assert result.warmed_up is False

    def test_windows_do_not_leak_between_zones(self):
        """
        Two services tracking two rooms must not share a
        window, or one room's count would smooth the other's.
        """

        from vision.service import VisionService

        busy = VisionService(detector=StubDetector([46]))
        empty = VisionService(detector=StubDetector([0]))

        for _ in range(5):
            busy.process_frame(b"frame")

        result = empty.process_frame(b"frame")

        assert result.smoothed_count == 0

    def test_window_size_zero_is_rejected(self):
        from vision.service import VisionService

        with pytest.raises(ValueError):
            VisionService(window_size=0)

    def test_result_serialises(self):
        from vision.service import VisionService

        service = VisionService(
            detector=StubDetector([46])
        )

        payload = service.process_frame(b"frame").as_dict()

        assert payload["raw_count"] == 46
        assert payload["smoothed_count"] == 46
        assert payload["window"] == [46]
        assert payload["warmed_up"] is False


# ============================================================
# VIDEO
# ============================================================


def _write_video(path: Path, frame_count: int = 8):
    """Builds a small video from solid frames."""

    import cv2
    import numpy as np

    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10,
        (160, 120),
    )

    for index in range(frame_count):
        value = 40 + index * 10

        writer.write(
            np.full((120, 160, 3), value, dtype=np.uint8)
        )

    writer.release()

    return path


class TestVideo:
    @requires_opencv
    def test_counts_frames_in_a_video(self, tmp_path):
        """
        The whole point of the video path: several frames are
        analysed and one stable figure is reported, rather than
        the count from whichever frame was decoded last.
        """

        from vision.service import VisionService

        video = _write_video(tmp_path / "clip.mp4")

        service = VisionService(
            detector=StubDetector([0])
        )

        result = service.count_people(video)

        assert result["frames_analysed"] == 8
        assert result["count"] == 0
        assert len(result["per_frame"]) == 8

    @requires_opencv
    def test_max_frames_caps_the_work(self, tmp_path):
        from vision.service import VisionService

        video = _write_video(tmp_path / "clip.mp4")

        result = VisionService(
            detector=StubDetector([0])
        ).count_people(video, max_frames=3)

        assert result["frames_analysed"] == 3

    @requires_opencv
    def test_sampling_skips_frames(self, tmp_path):
        from vision.service import VisionService

        video = _write_video(tmp_path / "clip.mp4")

        result = VisionService(
            detector=StubDetector([0])
        ).count_people(video, sample_every=2)

        assert result["frames_analysed"] == 4

    @requires_opencv
    def test_smoothing_survives_a_bad_frame_in_video(
        self, tmp_path,
    ):
        """
        One misdetected frame must not decide the clip's count.
        """

        from vision.service import VisionService

        video = _write_video(tmp_path / "clip.mp4")

        result = VisionService(
            detector=StubDetector(
                [12, 12, 12, 12, 0]
            )
        ).count_people(video)

        assert result["count"] == 12
        assert result["min_count"] == 0
        assert result["max_count"] == 12

    @requires_opencv
    def test_reports_spread_and_stability(self, tmp_path):
        """
        A wide spread means the estimate rests on a scene the
        camera struggled with, which is different from a stable
        scene that genuinely holds this many people.
        """

        from vision.service import VisionService

        video = _write_video(tmp_path / "clip.mp4")

        result = VisionService(
            detector=StubDetector([10, 10, 14, 10])
        ).count_people(video)

        assert result["min_count"] == 10
        assert result["max_count"] == 14
        assert result["stability"] > 0

    @requires_opencv
    def test_missing_video_raises(self, tmp_path):
        from vision.service import (
            VideoUnavailableError,
            VisionService,
        )

        with pytest.raises(VideoUnavailableError):
            VisionService(
                detector=StubDetector([0])
            ).count_people(tmp_path / "absent.mp4")

    @requires_opencv
    def test_non_video_file_raises(self, tmp_path):
        """
        A file that is not a video must fail loudly rather than
        report zero people, which would read as an empty room.
        """

        from vision.service import (
            VideoUnavailableError,
            VisionService,
        )

        broken = tmp_path / "broken.mp4"
        broken.write_bytes(b"this is not a video")

        with pytest.raises(VideoUnavailableError):
            VisionService(
                detector=StubDetector([0])
            ).count_people(broken)

    def test_sample_every_zero_is_rejected(self):
        from vision.service import VisionService

        with pytest.raises(ValueError):
            VisionService(
                detector=StubDetector([0])
            ).count_people("unused.mp4", sample_every=0)