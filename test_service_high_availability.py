import time
import pytest
import grpc
from MessageBroker import CircuitBreaker, ServiceHA

class DummyInstance:
    def __init__(self, name, fail_times=0):
        self.target = name
        self.breaker = CircuitBreaker(max_failures=2, reset_timeout=1)
        self._calls = 0
        self.fail_times = fail_times

    def call_rpc(self, rpc_name, request, timeout=5.0):
        self._calls += 1
        if self._calls <= self.fail_times:
            raise grpc.RpcError(f"simulated fail {self._calls}")
        return f"ok-{self.target}-{rpc_name}-{self._calls}"

def test_circuit_breaker_trip_and_recover():
    cb = CircuitBreaker(max_failures=2, reset_timeout=0.3)
    assert cb.is_available()
    cb.record_failure()
    assert cb.is_available()
    cb.record_failure()  # should trip
    assert not cb.is_available()
    time.sleep(0.35)
    # half-open allowed
    assert cb.is_available()
    cb.record_success()
    assert cb.is_available()

def test_service_ha_failover_success_after_failures():
    a = DummyInstance("a", fail_times=2)  # will fail twice then succeed
    b = DummyInstance("b", fail_times=0)  # always succeed
    ha = ServiceHA.__new__(ServiceHA)
    ha.instances = [a, b]
    import itertools, threading, logging
    ha._idx = itertools.cycle(range(len(ha.instances)))
    ha._global_lock = threading.Lock()
    ha._logger = logging.getLogger("test")
    res = ha.call("SomeRpc", object(), timeout=0.1)
    assert "ok-b" in res

def test_service_ha_honors_circuit_open():
    a = DummyInstance("a", fail_times=3)
    b = DummyInstance("b", fail_times=3)
    ha = ServiceHA.__new__(ServiceHA)
    ha.instances = [a, b]
    import itertools, threading, logging
    ha._idx = itertools.cycle(range(len(ha.instances)))
    ha._global_lock = threading.Lock()
    ha._logger = logging.getLogger("test")
    with pytest.raises(Exception):
        ha.call("SomeRpc", object(), timeout=0.1)