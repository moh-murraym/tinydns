
import time
from . import files

MAX_LEASE = 60 * 60 * 24 * 7 * 52  # 1 year in seconds


class Leases(object):
    """
    The Leases object represents a set of DHCPd leases. It takes a lease
    file as it's only initialization argument.

        :param: file_name: DHCPd Lease File (e.g. /var/lib/dhcp/dhcpd.leases)
    """
    def __init__(self, file_name):
        self.leases = []
        current_lease = None
        for line in files.yield_lines(file_name):
            line = line.strip()
            if line.startswith('#') or line == '':
                continue
            elif line.startswith('lease ') and current_lease is None:
                current_lease = Lease(line)
            elif line.startswith('}') and current_lease is not None:
                self.leases.append(current_lease)
                current_lease = None
            elif current_lease is not None:
                current_lease.add_line(line)
            else:
                continue
        self.leases.sort()
        self.leases.reverse()

    def has_key(self, mac):
        match = False
        for lease in self.leases:
            if lease.mac == mac:
                match = True
                break
        return match

    def __getitem__(self, mac):
        for lease in self.leases:
            if lease.mac == mac:
                return lease
        raise KeyError('MAC {} not found in leases.'.format(mac))

    def __iter__(self):
        return iter(self.leases)

    def yield_unique(self):
        reported = []
        for lease in self.leases:
            if (lease.host_name, lease.ip) in reported:
                continue
            else:
                reported.append((lease.host_name, lease.ip))
                yield lease


class Lease(object):
    """
    A single lease as issued by DHCPd and read from the a lease file
    """
    def __init__(self, line):
        self.ip = line.split()[1]
        self.mac = None
        self.expiration = None
        self.host_name = None

    def __cmp__(self, other):
        """The lease that compares highest is the one with that expires last.
        """
        if other is None:
            return 1
        return cmp(self.expiration, other.expiration)

    def __eq__(self, other):
        return self.mac == other.mac  # and self.expiration == self.expiration

    def __lt__(self, other):
        if other is None:
            return 1
        return self.expiration < other.expiration

    def add_line(self, line):
        fields = line[:-1].split()  # Get rid of trailing ";" before split.
        if fields[0] == 'ends':
            if len(fields) <= 3:
                self.expiration = time.time() + MAX_LEASE
            else:
                timestamp = ' '.join((fields[2], fields[3]))
                self.expiration = time.mktime(
                    time.strptime(timestamp, '%Y/%m/%d %H:%M:%S')
                    )
        elif fields[0:2] == ['hardware', 'ethernet']:
            self.mac = fields[2]
        elif fields[0] == 'client-hostname':
            self.set_host_name(fields[1])

    def set_host_name(self, host_name):
        for character in ('"', "'"):
            host_name = host_name.replace(character, '')
        for character in ('/', '\\', '_', ' '):
            host_name = host_name.replace(character, '-')
        while host_name.startswith('-'):
            host_name = host_name[1:]
        if host_name == '':
            return
        self.host_name = host_name.lower()
