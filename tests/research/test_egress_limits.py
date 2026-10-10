def test_proxy_defaults_match_research_values():
    from apps.research.egress import MAX_RESPONSE_BYTES, LocalEgressProxy

    proxy = LocalEgressProxy()
    assert proxy.tunnel_seconds == 30.0
    assert proxy.max_bytes == MAX_RESPONSE_BYTES


def test_proxy_accepts_portal_sized_limits():
    from apps.research.egress import LocalEgressProxy

    proxy = LocalEgressProxy(tunnel_seconds=900.0, max_bytes=100 * 1024 * 1024)
    assert proxy.tunnel_seconds == 900.0
    assert proxy.max_bytes == 100 * 1024 * 1024


def test_tunnel_stops_transferring_once_max_bytes_is_exceeded():
    """A regression that re-hardcoded MAX_RESPONSE_BYTES in _tunnel fails here."""
    import socket
    import time

    from apps.research.egress import LocalEgressProxy

    proxy = LocalEgressProxy(max_bytes=10)
    client_a, client_b = socket.socketpair()
    upstream_a, upstream_b = socket.socketpair()
    try:
        client_b.sendall(b"x" * 100)  # far more than the 10-byte cap
        started = time.monotonic()
        proxy._tunnel(client_a, upstream_a)
        # It returns because the cap was exceeded, not because the 30s
        # deadline elapsed.
        assert time.monotonic() - started < 5
    finally:
        for sock in (client_a, client_b, upstream_a, upstream_b):
            sock.close()


def test_tunnel_gives_up_when_the_deadline_elapses():
    """A regression that re-hardcoded 30 in _tunnel would hang here well past 5s."""
    import socket
    import time

    from apps.research.egress import LocalEgressProxy

    proxy = LocalEgressProxy(tunnel_seconds=0.2)
    client_a, client_b = socket.socketpair()
    upstream_a, upstream_b = socket.socketpair()
    try:
        started = time.monotonic()
        proxy._tunnel(client_a, upstream_a)  # no data ever flows
        elapsed = time.monotonic() - started
        assert elapsed < 5, f"tunnel ignored its deadline, ran {elapsed:.1f}s"
    finally:
        for sock in (client_a, client_b, upstream_a, upstream_b):
            sock.close()
