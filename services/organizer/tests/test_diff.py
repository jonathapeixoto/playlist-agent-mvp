from services.organizer.diff import diff_positions


def test_diff_positions_and_moved_count():
    diff = diff_positions(["a", "b", "c"], ["c", "b", "a"])
    assert diff.previous_positions == [2, 1, 0]
    assert diff.moved == 2


def test_diff_handles_duplicates_and_new_tracks():
    diff = diff_positions(["a", "a", "b"], ["a", "b", "a", "z"])
    assert diff.previous_positions == [0, 2, 1, None]
