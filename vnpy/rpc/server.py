import threading
import traceback
from time import time
from typing import Any, Callable, Dict, Optional

import zmq

from .common import HEARTBEAT_TOPIC, HEARTBEAT_INTERVAL


class RpcServer:
    """"""

    def __init__(self) -> None:
        """
        Constructor
        Initialize RPC server with ZMQ sockets and threading components.

        Initializes:
        - Function registry dictionary
        - ZMQ context and sockets (REP/PUB)
        - Threading components with proper synchronization
        - Heartbeat tracking
        """
        # Save functions dict: key is function name, value is function object
        self._functions: Dict[str, Callable] = {}

        # Zmq port related
        self._context: zmq.Context = zmq.Context()

        # Reply socket (Request–reply pattern)
        self._socket_rep: zmq.Socket = self._context.socket(zmq.REP)

        # Publish socket (Publish–subscribe pattern)
        self._socket_pub: zmq.Socket = self._context.socket(zmq.PUB)

        # Worker thread related
        self._active: bool = False                      # RpcServer status
        self._thread: Optional[threading.Thread] = None           # RpcServer thread
        self._lock: threading.Lock = threading.Lock()

        # Heartbeat related
        self._heartbeat_at: Optional[int] = None

    def is_active(self) -> bool:
        """"""
        return self._active

    def start(
        self,
        rep_address: str,
        pub_address: str,
    ) -> None:
        """
        Start RpcServer
        """
        if self._active:
            return

        # Bind socket address
        self._socket_rep.bind(rep_address)
        self._socket_pub.bind(pub_address)

        # Start RpcServer status
        self._active = True

        # Start RpcServer thread
        self._thread = threading.Thread(target=self.run)
        self._thread.start()

        # Init heartbeat publish timestamp
        self._heartbeat_at = time() + HEARTBEAT_INTERVAL

    def stop(self) -> None:
        """
        Stop RpcServer
        """
        if not self._active:
            return

        # Stop RpcServer status
        self._active = False

    def join(self) -> None:
        # Wait for RpcServer thread to exit
        if self._thread and self._thread.is_alive():
            self._thread.join()
        self._thread = None

    def run(self) -> None:
        """
        Run RpcServer functions
        """
        while self._active:
            # Poll response socket for 1 second
            n: int = self._socket_rep.poll(1000)
            self.check_heartbeat()

            if not n:
                continue

            # Receive request data from Reply socket
            req = self._socket_rep.recv_pyobj()

            # Get function name and parameters
            name, args, kwargs = req

            # Try to get and execute callable function object; capture exception information if it fails
            try:
                func: Callable = self._functions[name]
                r: Any = func(*args, **kwargs)
                rep: list = [True, r]
            except Exception as e:  # noqa
                rep: list = [False, traceback.format_exc()]

            # send callable response by Reply socket
            self._socket_rep.send_pyobj(rep)

        # Unbind socket address
        self._socket_pub.unbind(self._socket_pub.LAST_ENDPOINT)
        self._socket_rep.unbind(self._socket_rep.LAST_ENDPOINT)

    def publish(self, topic: str, data: Any) -> None:
        """
        Publish data
        """
        with self._lock:
            self._socket_pub.send_pyobj([topic, data])

    def register(self, func: Callable) -> None:
        """
        Register function
        """
        self._functions[func.__name__] = func

    def check_heartbeat(self) -> None:
        """
        Check whether it is required to send heartbeat.
        """
        now: float = time()
        if now >= self._heartbeat_at:
            # Publish heartbeat
            self.publish(HEARTBEAT_TOPIC, now)

            # Update timestamp of next publish
            self._heartbeat_at = now + HEARTBEAT_INTERVAL
