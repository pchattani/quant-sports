from oddsmarkets.powerlifting import canon


def test_dots_round_trip_a_known_total():
    # a 100 kg man totalling 700 kg is a published-range DOTS score; inverting recovers the total
    pts = canon.dots("M", 100.0, 700.0)
    assert 400 < pts < 600
    assert abs(canon.total_from_dots("M", 100.0, pts) - 700.0) < 0.05


def test_dots_women_are_not_the_mens_polynomial():
    assert canon.dots("F", 75.0, 400.0) != canon.dots("M", 75.0, 400.0)


def test_bodyweight_is_clamped():
    assert canon.dots_coeff("M", 10.0) == canon.dots_coeff("M", 40.0)
    assert canon.dots_coeff("M", 400.0) == canon.dots_coeff("M", 210.0)


def test_pid_and_meet_id_are_stable():
    assert canon.pid("Jane Doe #1") == canon.pid("Jane Doe #1")
    assert canon.pid("Jane Doe #1") != canon.pid("Jane Doe #2")
    a = canon.meet_id("USAPL", "2024-03-01", "Nationals", "USA")
    b = canon.meet_id("USAPL", "2024-03-01", "Nationals", "USA")
    assert a == b and len(a) == 16
