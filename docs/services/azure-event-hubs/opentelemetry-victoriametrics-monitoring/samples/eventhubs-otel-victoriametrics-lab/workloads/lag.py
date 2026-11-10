from dataclasses import dataclass


@dataclass(frozen=True)
class LagResult:
    messages: int | None
    checkpoint_present: bool
    partition_empty: bool
    invalid_order: bool = False


def compute_lag(
    last_enqueued_sequence_number: int | None,
    checkpoint_sequence_number: int | None,
) -> LagResult:
    """Return consumer backlog without inventing a value for a missing checkpoint."""
    if last_enqueued_sequence_number is None:
        # The service reports an empty partition as -1; a missing value means the lag is unknown.
        return LagResult(
            messages=None,
            checkpoint_present=checkpoint_sequence_number is not None,
            partition_empty=False,
        )
    if last_enqueued_sequence_number < 0:
        # An empty partition with a checkpoint past its last sequence number is still inverted.
        return LagResult(
            messages=0,
            checkpoint_present=checkpoint_sequence_number is not None,
            partition_empty=True,
            invalid_order=(
                checkpoint_sequence_number is not None
                and checkpoint_sequence_number > last_enqueued_sequence_number
            ),
        )

    if checkpoint_sequence_number is None:
        return LagResult(
            messages=None,
            checkpoint_present=False,
            partition_empty=False,
        )

    if checkpoint_sequence_number > last_enqueued_sequence_number:
        return LagResult(
            messages=0,
            checkpoint_present=True,
            partition_empty=False,
            invalid_order=True,
        )

    return LagResult(
        messages=last_enqueued_sequence_number - checkpoint_sequence_number,
        checkpoint_present=True,
        partition_empty=False,
    )
