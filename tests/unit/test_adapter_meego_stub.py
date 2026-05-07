# tests/unit/test_adapter_meego_stub.py
import pytest
from clonemate.adapters.meego import MeegoStub


def test_meego_stub_raises_not_implemented():
    stub = MeegoStub()
    assert stub.name == "meego"
    with pytest.raises(NotImplementedError) as exc:
        stub.fetch(None)
    assert "plugin" in str(exc.value).lower()
