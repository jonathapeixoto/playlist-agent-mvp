from pathlib import Path

from services.agent.undo import MEMORIA, UndoStore


def test_save_get_delete():
    store = UndoStore(":memory:")
    undo_id = store.save("p1", ["spotify:track:a", "spotify:track:b"])
    assert store.get(undo_id) == ("p1", ["spotify:track:a", "spotify:track:b"])
    store.delete(undo_id)
    assert store.get(undo_id) is None


def test_ids_are_unique():
    store = UndoStore(":memory:")
    assert store.save("p", []) != store.save("p", [])


def test_memory_database_creates_no_directory():
    store = UndoStore(MEMORIA)
    undo_id = store.save("p", ["spotify:track:a"])
    assert store.get(undo_id) == ("p", ["spotify:track:a"])
    assert not Path(MEMORIA).exists()
