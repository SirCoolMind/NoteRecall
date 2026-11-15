import socket

import port


def _hold(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", p))
    s.listen(1)
    return s


def _free_run(n):
    """A start port with n free ports after it (tests must not assume 8756 is free)."""
    for start in range(20000, 30000, 50):
        if all(port.is_free("127.0.0.1", start + i) for i in range(n)):
            return start
    raise RuntimeError("no free range")


def test_free_port_is_kept():
    start = _free_run(3)
    assert port.pick("127.0.0.1", start) == start


def test_taken_port_moves_up_to_the_next_free_one():
    start = _free_run(3)
    a, b = _hold(start), _hold(start + 1)
    try:
        assert port.pick("127.0.0.1", start) == start + 2
    finally:
        a.close(); b.close()


def test_nothing_free_returns_the_wanted_port_so_the_error_names_it():
    start = _free_run(2)
    a, b = _hold(start), _hold(start + 1)
    try:
        assert port.pick("127.0.0.1", start, tries=2) == start
    finally:
        a.close(); b.close()
