import hmac

from walnut.pin import PinGate

KEY = b"k" * 32


def gate(t, pin_hash=None):
    h = hmac.new(KEY, b"482916", "sha256").hexdigest() if pin_hash is None else pin_hash
    return PinGate(h, KEY, clock=lambda: t[0])


def test_pin_ok_and_lockout():
    t = [0.0]
    g = gate(t)
    assert g.check("482916")
    for _ in range(5):
        assert not g.check("000000")
    assert g.locked_for() == 60 and not g.check("482916")
    t[0] = 60.0
    assert g.locked_for() == 0
    assert g.check("482916")


def test_success_resets_failures():
    t = [0.0]
    g = gate(t)
    for _ in range(4):
        assert not g.check("1")
    assert g.check("482916")
    for _ in range(4):
        assert not g.check("1")
    assert g.locked_for() == 0


def test_locked_check_does_not_extend_lock():
    t = [0.0]
    g = gate(t)
    for _ in range(5):
        g.check("1")
    t[0] = 30.0
    assert not g.check("1")
    assert g.locked_for() == 30


def test_empty_hash_never_passes():
    t = [0.0]
    g = gate(t, pin_hash="")
    assert not g.check("")
    assert not g.check("482916")
