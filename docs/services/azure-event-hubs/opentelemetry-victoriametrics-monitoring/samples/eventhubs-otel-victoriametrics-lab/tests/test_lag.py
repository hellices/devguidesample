import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "workloads"))

from lag import LagResult, compute_lag


def test_lag_is_sequence_difference():
    assert compute_lag(120, 99) == LagResult(
        messages=21,
        checkpoint_present=True,
        partition_empty=False,
    )


def test_missing_checkpoint_is_reported_not_coerced_to_zero():
    assert compute_lag(120, None) == LagResult(
        messages=None,
        checkpoint_present=False,
        partition_empty=False,
    )


def test_unknown_last_sequence_is_unknown_lag_not_an_empty_partition():
    assert compute_lag(None, None) == LagResult(messages=None, checkpoint_present=False, partition_empty=False)
    assert compute_lag(None, 10) == LagResult(messages=None, checkpoint_present=True, partition_empty=False)


def test_empty_partition_has_zero_lag():
    assert compute_lag(-1, None) == LagResult(
        messages=0,
        checkpoint_present=False,
        partition_empty=True,
    )


def test_checkpoint_ahead_is_clamped_and_marked_invalid():
    assert compute_lag(10, 11) == LagResult(
        messages=0,
        checkpoint_present=True,
        partition_empty=False,
        invalid_order=True,
    )


def test_equal_checkpoint_and_last_sequence_has_zero_lag():
    assert compute_lag(10, 10) == LagResult(
        messages=0,
        checkpoint_present=True,
        partition_empty=False,
    )


def test_empty_partition_with_a_checkpoint_past_its_end_is_marked_invalid():
    assert compute_lag(-1, 0) == LagResult(
        messages=0, checkpoint_present=True, partition_empty=True, invalid_order=True
    )
    assert compute_lag(-1, -1) == LagResult(
        messages=0, checkpoint_present=True, partition_empty=True, invalid_order=False
    )
    assert compute_lag(-1, None) == LagResult(
        messages=0, checkpoint_present=False, partition_empty=True, invalid_order=False
    )
