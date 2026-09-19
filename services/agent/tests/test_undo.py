from services.agent.undo import UndoStore


def test_save_get_delete(tmp_path):
    store = UndoStore(tmp_path / "u.sqlite")
    undo_id = store.save("p1", ["spotify:track:a", "spotify:track:b"])
    assert store.get(undo_id) == ("p1", ["spotify:track:a", "spotify:track:b"])
    store.delete(undo_id)
    assert store.get(undo_id) is None


def test_ids_are_unique(tmp_path):
    store = UndoStore(tmp_path / "u.sqlite")
    assert store.save("p", []) != store.save("p", [])
