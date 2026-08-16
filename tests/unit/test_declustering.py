from datetime import UTC, datetime, timedelta

import numpy as np

from chile_oef.seismicity.declustering import (
    DeclusteringPolicy,
    EventForDeclustering,
    decluster,
)


def test_empty_catalog() -> None:
    result = decluster([], b_value=1.0)
    assert result.event_count == 0
    assert result.classifications == ()
    assert result.log_eta_threshold is None


def test_first_event_chronologically_is_trivially_background() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        EventForDeclustering(
            event_id=f"e{i}",
            event_time=base + timedelta(days=i),
            latitude=-33.0,
            longitude=-71.0,
            magnitude=3.5,
        )
        for i in range(5)
    ]
    result = decluster(events, b_value=1.0)
    first = next(c for c in result.classifications if c.event_id == "e0")
    assert first.is_background is True
    assert first.parent_event_id is None
    assert first.log10_eta is None


def test_below_minimum_sample_leaves_events_unclassified() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        EventForDeclustering(
            event_id=f"e{i}",
            event_time=base + timedelta(days=i),
            latitude=-33.0,
            longitude=-71.0,
            magnitude=3.5,
        )
        for i in range(10)
    ]
    policy = DeclusteringPolicy(minimum_events_for_threshold_fit=50)
    result = decluster(events, b_value=1.0, policy=policy)
    assert result.log_eta_threshold is None
    # The first event is always trivially background regardless of the
    # threshold fit; every subsequent event with an unfit threshold is
    # explicitly unclassified (None), not defaulted to either class.
    non_first = [c for c in result.classifications if c.event_id != "e0"]
    assert all(c.is_background is None for c in non_first)
    assert result.classified_event_count == 1


def _synthetic_background_and_aftershock_catalog(
    *, seed: int, b_value: float
) -> tuple[list[EventForDeclustering], set[str], set[str]]:
    """Background events scattered uniformly in space/time over two years,
    plus tight aftershock sequences clustered in space and time right after
    a handful of mainshocks. Mirrors the generative assumption nearest-
    neighbor declustering is built on (Baiesi & Paczuski 2004; Zaliapin &
    Ben-Zion 2013), used here to check the implementation recovers the known
    ground truth, not to claim precision on real, unlabeled catalogs.
    """
    rng = np.random.default_rng(seed)
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    events: list[EventForDeclustering] = []
    background_ids: set[str] = set()
    triggered_ids: set[str] = set()

    background_count = 150
    bg_times = rng.uniform(0, 730, size=background_count)
    bg_lat = rng.uniform(-34.0, -32.0, size=background_count)
    bg_lon = rng.uniform(-72.0, -70.0, size=background_count)
    bg_mag = np.clip(3.0 + rng.exponential(1.0 / b_value, size=background_count), 3.0, 6.0)
    for i in range(background_count):
        event_id = f"bg-{i}"
        events.append(
            EventForDeclustering(
                event_id=event_id,
                event_time=t0 + timedelta(days=float(bg_times[i])),
                latitude=float(bg_lat[i]),
                longitude=float(bg_lon[i]),
                magnitude=float(bg_mag[i]),
            )
        )
        background_ids.add(event_id)

    for cluster in range(3):
        main_time = rng.uniform(0, 700)
        main_lat, main_lon = rng.uniform(-34.0, -32.0), rng.uniform(-72.0, -70.0)
        main_id = f"main-{cluster}"
        events.append(
            EventForDeclustering(
                event_id=main_id,
                event_time=t0 + timedelta(days=float(main_time)),
                latitude=float(main_lat),
                longitude=float(main_lon),
                magnitude=5.5,
            )
        )
        background_ids.add(main_id)  # a mainshock is itself independent

        aftershock_count = 25
        after_dt = rng.exponential(2.0, size=aftershock_count)
        after_lat = main_lat + rng.normal(0, 0.02, size=aftershock_count)
        after_lon = main_lon + rng.normal(0, 0.02, size=aftershock_count)
        after_mag = np.clip(3.0 + rng.exponential(1.0 / b_value, size=aftershock_count), 3.0, 5.0)
        for i in range(aftershock_count):
            event_id = f"after-{cluster}-{i}"
            events.append(
                EventForDeclustering(
                    event_id=event_id,
                    event_time=t0 + timedelta(days=float(main_time + after_dt[i])),
                    latitude=float(after_lat[i]),
                    longitude=float(after_lon[i]),
                    magnitude=float(after_mag[i]),
                )
            )
            triggered_ids.add(event_id)

    return events, background_ids, triggered_ids


def test_recovers_background_and_triggered_events_on_synthetic_catalog() -> None:
    b_value = 1.0
    events, background_ids, triggered_ids = _synthetic_background_and_aftershock_catalog(
        seed=5, b_value=b_value
    )
    result = decluster(events, b_value=b_value, policy=DeclusteringPolicy(fractal_dimension=1.6))

    assert result.event_count == len(events)
    assert result.log_eta_threshold is not None
    by_id = {c.event_id: c for c in result.classifications}

    background_correct = sum(1 for eid in background_ids if by_id[eid].is_background)
    triggered_correct = sum(1 for eid in triggered_ids if by_id[eid].is_background is False)

    # Loose accuracy bounds -- the point is that the algorithm separates the
    # two known populations well above chance, not that it is perfect on a
    # single seeded draw.
    assert background_correct / len(background_ids) > 0.85
    assert triggered_correct / len(triggered_ids) > 0.9
    assert result.diagnostics["mu_triggered"] < result.diagnostics["mu_background"]


def test_zero_distance_and_zero_time_events_do_not_crash() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        EventForDeclustering(
            event_id=f"e{i}", event_time=base, latitude=-33.0, longitude=-71.0, magnitude=3.5
        )
        for i in range(60)
    ]
    result = decluster(events, b_value=1.0)
    assert result.event_count == 60
    assert all(
        c.log10_eta is None or (c.log10_eta == c.log10_eta) for c in result.classifications
    )  # no NaN
