# Design: stable MJPEG bitrate

## Context

See `proposal.md`. The default MJPEG encoder factory creates `MJPEGEncoder()`
with no bitrate. picamera2's `start_encoder` sets the encoder's nominal
framerate to `1000000 / max(FrameDurationLimits.min, 33333)` (capped at 30),
and `MJPEGEncoder._setup` scales the reference 30 Mbps (Quality.MEDIUM) by
`(width·height·framerate) / (1920·1080·30)`. In the 4608x2592 sensor mode the
min frame duration is ~69.7 ms (~14.35 fps), so the 1280x720 lores stream gets
~6.4 Mbps instead of ~13.3 Mbps — half the bitrate on a noisier, un-binned
source, producing visible macroblocking.

## Goals / Non-Goals

Goals:
- Live view quality independent of the sensor mode / frame rate.
- Minimal, production-only change (tests already inject encoder fakes).

Non-goals:
- Configuring the bitrate per camera or via config.yaml (fixed constant).
- Changing the lores sizing or sensor mode selection.

## Decisions

1. **Pin `MJPEGEncoder(bitrate=20_000_000)` in `_default_mjpeg_encoder_factory`.**
   Rationale: picamera2 only recomputes the bitrate when
   `quality is not None or bitrate is None` — an explicit bitrate is honored
   verbatim, so the framerate-driven collapse is impossible. 20 Mbps is ~1.5x
   the current 30fps-mode bitrate and ~3x the 4K-mode bitrate, giving clean 720p
   headroom for the noisy native-4K source. The encoded stream is fanned out to
   all subscribers, so it is shared bandwidth regardless of viewer count.
   Alternatives: `quality=Quality.HIGH` at `start_encoder` — rejected, it still
   scales by the nominal framerate and would yield only ~8.5 Mbps at 4K.

2. **Expose the value as a module constant `MJPEG_BITRATE`.**
   Rationale: self-documenting and trivially tunable; no config plumbing.

3. **Add a unit test** that the default factory produces an encoder with the
   pinned bitrate, by constructing it behind a stubbed `picamera2.encoders`
   module if importable in the test env; otherwise assert via the constant in
   the factory's behavior only where straightforward. (See tasks.)

## Risks / Trade-offs

- **Higher bandwidth**: ~20 Mbps per encoder stream vs ~13 Mbps before.
  → Shared across all viewers; LAN-only; acceptable.
- **Wasted bitrate in clean, slow scenes**: MJPEG with a fixed bitrate uses
  what it needs; no practical downside at this magnitude.

## Migration Plan

Deploy via the existing Ansible playbook (source sync + service restart).
Rollback: revert the factory change and re-run the playbook.

## Open Questions

None.
