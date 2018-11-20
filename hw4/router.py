import os.path
import socket
import table
import threading
import util
import sys
import struct

_CONFIG_UPDATE_INTERVAL_SEC = 5

_MAX_UPDATE_MSG_SIZE = 1024
_BASE_ID = 8000
INF = 65535

def _ToPort(router_id):
  return _BASE_ID + router_id

def _ToRouterId(port):
  return port - _BASE_ID


class Router:
  def __init__(self, config_filename):
    # ForwardingTable has 3 columns (DestinationId,NextHop,Cost). It's
    # threadsafe.
    self._forwarding_table = table.ForwardingTable()
    # Config file has router_id, neighbors, and link cost to reach
    # them.
    self._config_filename = config_filename
    self._router_id = None
    # Socket used to send/recv update messages (using UDP).
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.host_name = socket.getfqdn()
    self.host_ip = socket.gethostbyname(self.host_name)
    self._neighbors = {}
    self._nodes = set()
    self._costs = {}


  def start(self):
    # Start a periodic closure to update config.
    self._config_updater = util.PeriodicClosure(
        self.load_config, _CONFIG_UPDATE_INTERVAL_SEC)
    self._config_updater.start()
    # TODO: init and start other threads.
    # host_port = _ToPort(self._router_id)
    # self._socket.bind(self.host_ip, host_port)

    while True: 
      data, addr = self._socket.recvfrom(1024)
      src_id = _ToRouterId(addr[1])
      ls_pair = self.unpack(data)
      self.update_from_neighbor(ls_pair, src_id)

  
    

  def stop(self):
    if self._config_updater:
      self._config_updater.stop()
    # TODO: clean up other threads.


  def load_config(self):
    assert os.path.isfile(self._config_filename)
    with open(self._config_filename, 'r') as f:
      router_id = int(f.readline().strip())
      # Only set router_id when first initialize.
      if not self._router_id:
        self._socket.bind(('localhost', _ToPort(router_id)))
        self._router_id = router_id
        self._costs[router_id] = 0
        self._nodes.add(router_id)

      for line in f:
        neighbor, cost = map(int, line.strip().split(","))
        if neighbor not in self._nodes:
          self._nodes.add(neighbor)
        if neighbor not in self._neighbors:
          self._neighbors[neighbor] = {}
        if self.get_costs(neighbor) != cost:
          self._costs[neighbor] = cost
          self.update_info()

      print(self._forwarding_table)
      snapshot = self._forwarding_table.snapshot()
      data = self.pack(snapshot)

      for neighbor in self._neighbors:
        self.send(data, neighbor)          

  def send(self,send_data, send_id):
    server_ip = 'localhost'
    server_port = _ToPort(send_id)
    self._socket.sendto(send_data, (server_ip, server_port))

  def update_from_neighbor(self, ls_pair, src_id):
    for pair in ls_pair:
      dest = pair[0]
      cost = pair[1]
      if dest not in self._nodes:
        self._nodes.add(dest)
      self._neighbors[src_id][dest] = cost
      self.update_info()



  def update_info(self):
    snapshot = self.to_dict(self._forwarding_table.snapshot())
    for dest in self._nodes:
      if dest == self._router_id:
        snapshot[dest] = (self._router_id, 0)
      else:
        ls = []
        for neighbor in self._neighbors:
          ls.append((neighbor, self.get_costs(neighbor) + self.get_neighbors(neighbor, dest)))
        new_cost = min(ls, key=lambda x: x[1])
        snapshot[dest] = (new_cost[0], min(new_cost[1], INF))
    self._forwarding_table.reset(self.to_list(snapshot))
  
  def unpack(self,data):
    count = struct.unpack('!h',data[0:2])[0]
    ls = []
    for i in range(count):
      piece = data[2+i*4: 2+i*4+4]
      dest = struct.unpack('!h', piece[0:2])[0]
      cost = struct.unpack('!h', piece[2:4])[0]
      ls.append((dest, cost))
    return ls

  def pack(self, snapshot):
    data = b''
    data += struct.pack('!h', len(snapshot))
    for unit in snapshot:
      dest, nexthop, cost = unit
      data += struct.pack('!h', dest)
      data += struct.pack('!h', cost)
    return data

  def get_costs(self, dest):
    if dest in self._costs:
      return self._costs[dest]
    return INF

  def get_neighbors(self, neighbor, dest):
    if dest in self._neighbors[neighbor]:
      return self._neighbors[neighbor][dest]
    if dest == neighbor:
      return 0
    return INF

  def to_dict(self, snapshot: list):
    table = {}
    for dst, next, cost in snapshot:
      assert dst not in table
      table[dst] = (next, cost)
    return table

  def to_list(self, table: dict):
    snapshot = []
    for dest in table:
      next, cost = table[dest]
      snapshot.append((dest, next, cost))
    return snapshot


        



