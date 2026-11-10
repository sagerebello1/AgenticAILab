"""The research pipeline must not invent an acquisition probability."""
import os

import quote
from predictive.gates import acquisition_ready
from predictive.logistic import fit, probability
from predictive.status import public_status

ROOT = os.path.dirname(os.path.abspath(__file__))


def test_empty_flags_still_start_at_the_announced_base_rate():
    assert abs(quote.close_probability({})["close"] - quote.BASE_P) < 1e-9
    assert not os.path.exists(os.path.join(ROOT, "data", "model.json"))


def test_a_small_sample_does_not_clear_the_training_gate():
    ready, missing = acquisition_ready({"rows": 8, "positives": 4, "negatives": 4, "holdout": 0})
    assert ready is False
    assert "rows" in missing and "positives" in missing and "holdout" in missing


def test_logistic_math_is_not_saved_as_a_deal_model():
    rows = [[0.0, 0.0], [0.1, 0.0], [0.0, 0.2], [1.0, 1.0], [0.9, 1.1], [1.2, 0.8]]
    labels = [0, 0, 0, 1, 1, 1]
    weights = fit(rows, labels)
    low = sum(probability(weights, row) for row in rows[:3]) / 3
    high = sum(probability(weights, row) for row in rows[3:]) / 3
    assert high > low + 0.4
    assert not os.path.exists(os.path.join(ROOT, "data", "model.json"))


def test_public_status_has_no_probability_when_untrained():
    status = public_status()
    assert status["trained"] is False
    assert "acquisitionProbabilities" not in status
    assert all(not isinstance(value, float) for value in status.values())


if __name__ == "__main__":
    test_empty_flags_still_start_at_the_announced_base_rate()
    test_a_small_sample_does_not_clear_the_training_gate()
    test_logistic_math_is_not_saved_as_a_deal_model()
    test_public_status_has_no_probability_when_untrained()
    print("ok")
