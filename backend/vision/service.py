"""
Vision service: temporal smoothing over camera frames.

`PersonDetector` answers one question about one image: how many
people are visible right now. That is not the same question as
how many people are in the room, and treating it as though it
were produces occupancy figures that swing on a single frame.

A missed detection reads as a fall from 47 to 0. A phantom box
reads as a surge. Neither means the room changed. This module
sits between the detector and the caller, keeps a short window of
recent counts and reports a stable figure derived from all of
them, so an occupancy value describes the window rather than
whichever frame happened to arrive last.

It also reads video, which the detector deliberately does not:
`PersonDetector.detect` takes the bytes of one still image and
knows nothing about containers, frame rates or codecs. All of
that lives here, where it can be tested and reasoned about
separately.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Iterator, List, Optional, Union

from vision.config import (
    DEFAULT_SMOOTHING_WINDOW,
    SMOOTHING_METHOD,
)
from vision.detector import PersonDetector


logger = logging.getLogger(__name__)


# Extensions treated as video rather than a still image. The
# decoded content is what ultimately decides, but this keeps the
# common case from being probed twice.
VIDEO_SUFFIXES = frozenset(
    {".mp4", ".avi", ".mov", ".m4v", ".mkv", ".webm"}
)

# Frames are re-encoded to JPEG before detection, because the
# detector validates and decodes its input as a still image.
# Quality is high enough that re-encoding cannot change a
# detection; the alternative, threading raw frame buffers through
# the image validator, would bypass the validation the detector
# relies on.
FRAME_JPEG_QUALITY = 90


class VideoUnavailableError(Exception):
    """
    The video could not be opened or decoded.

    Raised instead of returning zero frames, because a silent
    zero reads as "the room was empty" when it actually means
    "nothing was analysed".
    """


@dataclass
class SmoothingResult:
    """
    One frame's observation, plus the window it sits in.
    """

    raw_count: int

    smoothed_count: int

    confidence: float

    # The window, oldest first. Useful for explaining a result:
    # a smoothed figure that disagrees with the newest frame is
    # only explicable by looking at what came before it.
    window: List[int] = field(default_factory=list)

    # False until the window holds enough samples to be worth
    # reporting. The count is still usable, it just rests on
    # fewer observations than intended.
    warmed_up: bool = False

    def as_dict(self) -> dict:
        return {
            "raw_count": self.raw_count,
            "smoothed_count": self.smoothed_count,
            "confidence": self.confidence,
            "window": list(self.window),
            "warmed_up": self.warmed_up,
        }


class VisionService:
    """
    Counts people across a sequence of frames and reports a
    stable figure.

    The smoothing window is per-instance. Two services tracking
    two different zones must not share one window, and an
    instance per zone is the simplest way to guarantee that.
    """

    def __init__(
        self,
        detector: Optional[PersonDetector] = None,
        window_size: int = DEFAULT_SMOOTHING_WINDOW,
    ):
        if window_size < 1:
            raise ValueError(
                "window_size must be at least 1; a window "
                "of zero frames has nothing to smooth"
            )

        self.detector = detector or PersonDetector()

        self.window_size = window_size

        self._counts: Deque[int] = deque(maxlen=window_size)

    # --- single frames -------------------------------------------

    def process_frame(
        self,
        frame: bytes,
        declared_content_type: Optional[str] = None,
    ) -> SmoothingResult:
        """
        Counts people in one frame and folds the result into the
        smoothing window.

        `frame` is the encoded bytes of a still image, which is
        what both `PersonDetector.detect` and `count_in_image`
        accept.
        """

        result = self.detector.detect(
            frame, declared_content_type=declared_content_type
        )

        return self._record(result.people_count, result.confidence)

    def _record(
        self,
        count: int,
        confidence: float,
    ) -> SmoothingResult:
        self._counts.append(count)

        window = list(self._counts)

        smoothed = int(
            sorted(window)[len(window) // 2]
        )

        # A one-frame window has nothing to smooth, so the
        # reported value is that frame's count and the result is
        # marked not warmed up.
        warmed_up = len(window) >= self.window_size

        return SmoothingResult(
            raw_count=count,
            smoothed_count=smoothed,
            confidence=confidence,
            window=window,
            warmed_up=warmed_up,
        )

    def reset(self) -> None:
        """
        Clears the window.

        Needed when the camera moves or the zone changes: the
        frames before that moment describe a different scene, and
        averaging across the change would report a figure for
        neither.
        """

        self._counts.clear()

    # --- still images --------------------------------------------

    def count_in_image(
        self,
        data: bytes,
        declared_content_type: Optional[str] = None,
    ) -> SmoothingResult:
        """Convenience wrapper for callers holding a still."""

        return self.process_frame(
            data, declared_content_type=declared_content_type
        )

    # --- video ---------------------------------------------------

    def count_people(
        self,
        source: Union[str, Path],
        max_frames: Optional[int] = None,
        sample_every: int = 1,
    ) -> dict:
        """
        Counts people across a video and returns a stable figure.

        `source` is a path to a video file. Every frame is
        analysed unless `max_frames` or `sample_every` narrows
        that, because counting is the expensive part and a long
        clip would otherwise run for minutes.

        `sample_every` keeps one frame in N. Sampling is safe
        here precisely because the result is smoothed across a
        window rather than taken from a single frame.

        The result is the smoothed count over the frames that
        were analysed, together with the per-frame counts so a
        caller can see how stable the estimate was.
        """

        if sample_every < 1:
            raise ValueError("sample_every must be at least 1")

        per_frame: List[dict] = []

        for index, frame in enumerate(
            self.iter_frames(
                source,
                max_frames=max_frames,
                sample_every=sample_every,
            )
        ):
            result = self.process_frame(
                frame, declared_content_type="image/jpeg"
            )

            per_frame.append(
                {
                    "frame": index,
                    "raw_count": result.raw_count,
                    "smoothed_count": result.smoothed_count,
                    "confidence": result.confidence,
                }
            )

        if not per_frame:
            raise VideoUnavailableError(
                "The video produced no analysable frames."
            )

        counts = [item["raw_count"] for item in per_frame]

        # The whole-clip figure is the median of the frame
        # counts, for the same reason the rolling figure is: one
        # misdetected frame must not be able to move it.
        clip_count = int(sorted(counts)[len(counts) // 2])

        confidences = [
            item["confidence"] for item in per_frame
        ]

        return {
            "count": clip_count,
            "confidence": round(
                sum(confidences) / len(confidences), 5
            ),
            "frames_analysed": len(per_frame),
            "min_count": min(counts),
            "max_count": max(counts),
            # A wide spread means the estimate is resting on a
            # scene the camera struggled with, which is different
            # from a stable scene that genuinely holds this many
            # people. Reporting it lets a caller tell those
            # apart instead of trusting a confident average.
            "stability": round(
                (max(counts) - min(counts)) / max(clip_count, 1),
                4,
            ),
            "per_frame": per_frame,
        }

    @staticmethod
    def iter_frames(
        source: Union[str, Path],
        max_frames: Optional[int] = None,
        sample_every: int = 1,
    ) -> Iterator[bytes]:
        """
        Yields encoded JPEG frames from a video file.

        OpenCV is imported here rather than at module scope so
        that importing this module does not require it. The
        detector deliberately has no OpenCV dependency, and the
        test suite should not need one just to exercise
        smoothing.
        """

        try:
            import cv2
        except ImportError as exc:  # pragma: no cover
            raise VideoUnavailableError(
                "opencv-python is required to read video. "
                "Install it with: pip install opencv-python"
            ) from exc

        path = Path(source)

        if not path.exists():
            raise VideoUnavailableError(
                f"Video not found: {path}"
            )

        capture = cv2.VideoCapture(str(path))

        if not capture.isOpened():
            capture.release()

            raise VideoUnavailableError(
                f"Could not open video: {path}"
            )

        produced = 0
        read = 0

        try:
            while True:
                if max_frames is not None and produced >= max_frames:
                    break

                ok, frame = capture.read()

                if not ok:
                    break

                read += 1

                if (read - 1) % sample_every:
                    continue

                ok, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), FRAME_JPEG_QUALITY],
                )

                if not ok:
                    continue

                produced += 1

                yield encoded.tobytes()
        finally:
            capture.release()

        if produced == 0:
            logger.warning(
                "No analysable frames decoded from %s", path
            )