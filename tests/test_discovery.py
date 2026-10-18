"""Finding loggers on the network (discovery.py), against a UDP responder on
the loopback interface."""

import asyncio

from custom_components.pylontech_easyconf import discovery


def test_a_logger_reply_is_parsed():
    found = discovery.parse_reply(b"192.168.1.221,E8FDF8A1B2C3,2712345678")
    assert found == discovery.FoundLogger("192.168.1.221", "E8:FD:F8:A1:B2:C3", 2712345678)


def test_other_traffic_on_the_port_is_ignored():
    assert discovery.parse_reply(b"+ok") is None
    assert discovery.parse_reply(b"192.168.1.5,AABBCCDDEEFF,not-a-serial") is None
    assert discovery.parse_reply(b"nonsense,AABBCCDDEEFF,123") is None


def test_broadcast_addresses_of_the_private_networks():
    nets = [("192.168.1.10", 24), ("10.0.5.3", 16), ("127.0.0.1", 8), ("8.8.8.8", 24),
            ("169.254.3.3", 16), ("192.168.1.11", 24)]
    assert discovery.broadcast_addresses(nets) == ["192.168.1.255", "10.0.255.255"]
    assert discovery.broadcast_addresses([]) == ["255.255.255.255"]


class _Responder(asyncio.DatagramProtocol):
    def __init__(self, replies):
        self.replies = replies
        self.greetings = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.greetings.append(data)
        if data == discovery.GREETINGS[0]:
            for reply in self.replies:
                self.transport.sendto(reply, addr)


def test_scan_collects_each_logger_once():
    async def go():
        loop = asyncio.get_running_loop()
        responder = _Responder([b"127.0.0.1,E8FDF8000001,1111111111",
                                b"127.0.0.1,E8FDF8000002,2222222222", b"garbage"])
        transport, _ = await loop.create_datagram_endpoint(
            lambda: responder, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        try:
            found = await discovery.scan(["127.0.0.1"], timeout=0.4, port=port)
        finally:
            transport.close()
        return found, responder.greetings

    found, greetings = asyncio.run(go())
    assert [f.serial for f in found] == [1111111111, 2222222222]
    assert set(greetings) == set(discovery.GREETINGS)
