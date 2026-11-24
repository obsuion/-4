import sys
def block_network():
    def deny(event, args):
        if event.startswith("socket.") or event == "urllib.Request":
            raise RuntimeError("Python network disabled for offline reconstruction")
    sys.addaudithook(deny)
    # Verify the guard without attempting a connection.
    import socket
    try:
        socket.getaddrinfo("example.invalid", 443)
    except RuntimeError:
        return
    raise AssertionError("network audit guard did not reject name resolution")
