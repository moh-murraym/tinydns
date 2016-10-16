#!/usr/bin/env python

import os
import time
import argparse

from ipaddress import ip_network as ipnet, ip_address as ipaddr

from tinydns import files, dhcpd, data as tinydata

# Utility Functions
CURRENT_TIME = time.time()
MAX_TTL = 24 * 60 * 60  # seconds
MIN_TTL = 60  # seconds
LINE_LENGTH = 79  # in characters

def calc_ttl(lease):
    ttl = int(lease.expiration - CURRENT_TIME)
    ttl = max(ttl, MIN_TTL)
    ttl = min(ttl, MAX_TTL)
    return str(ttl)


def dedot(dom):
    return dom.strip().lstrip('.')


def domain_getter(domain_map):
    dmap = list(domain_map.items())
    # sort the network addresses so that the larger networks come later
    # this way, we can define a smaller subnet that doesn't really
    # exist in dhcp to provide special names to sub machines
    dmap.sort(key=lambda x: x[0].network_address._ip + x[0].num_addresses)

    def _real_get_domain(ip):
        ipobj = ipaddr(ip)
        for cidr, domain in dmap:
            if ipobj in cidr:
                return domain
        return None
    return _real_get_domain


def dhcp_header(domain, spacer='='):
    msg = 'DHCP-Leased records for: {}'.format(domain)
    L = LINE_LENGTH - 19
    spacer_count = (L - len(msg) - 4) // 2
    if spacer_count > 0:
        tmpl = ' {spacer} {message} {spacer}'
    else:
        tmpl = ' {spacer}\n# {message}\n# {spacer}'
        spacer_count = L
    return tmpl.format(spacer=(spacer * spacer_count), message=msg)


def make_alias_entry(lease, host_name=None):
    hostname = lease.host_name if host_name is None else host_name
    domain_suffix = get_domain(lease.ip)
    fqdn = '.'.join((hostname, domain_suffix))
    entry = tinydata.Alias(fqdn, lease.ip, ttl=calc_ttl(lease))
    return (domain_suffix, entry)

# --- Read command-line options ---

parser = argparse.ArgumentParser(
    description='A utility to add dhcp-leased hosts to tinydns.'
    )
parser.add_argument(
    '-d', '--domain', nargs='?', required=False,
    help='''The domain to which hosts should belong. For example, if the
        domain is set to example.com then when the host jdoe is assigned
        an IP address via DHCP, it will be added to tinydns as
        jdoe.example.com.'''
    )
parser.add_argument(
    '-n', '--subnet-map', nargs='?', required=False,
    help='The path to a file which maps IP/Netmask prefixes to domains. '
    'The syntax is : <ip/netmask>    <domain> '
    'e.g. 192.168.12.0/26    dmz.example.com'
    )
parser.add_argument(
    '--dry-run', action='store_true',
    help="Don't modify tinydns data. Write to standard output instead."
    )
parser.add_argument(
    '-l', '--leases', nargs='?', default='/var/lib/dhcpd/dhcpd.leases',
    help='The location of the dhcpd leases file (default: %(default)s).'
    )
parser.add_argument(
    '-m', '--macfile', nargs='?',
    help='''The path to a file of hard-coded MAC address to hostname mappings.
        Each line in the file should contain a MAC address, then any amount of
        whitespace, then the host name. This is useful for hosts that do not
        provide their name to the DHCP server.
    '''
    )
parser.add_argument(
    '-r', '--root', nargs='?', default='/etc/djbdns/tinydns',
    help='The tinydns root directory (default: %(default)s).'
    )
parser.add_argument(
    '-s', '--static', nargs='*',
    help='''Files that contain static tinydns host information. These will
        be concatenated with the DHCP-derived information to create the
        tinydns data file. Files may be specified one after another separated
        by spaces, or through the use of command-line wildcards (default:
        ROOT/*.static).'''
    )

options = parser.parse_args()
if options.static is None:
    options.static = []
    if os.path.exists(options.root):
        for item in sorted(os.listdir(options.root)):
            if item.endswith('.static'):
                options.static.append(os.path.join(options.root, item))
domain_map = {}
if options.subnet_map:
    for line in files.yield_lines(options.subnet_map):
        i, d = line.split()
        domain_map[ipnet(i.strip())] = dedot(d)

if options.domain:
    options.domain = dedot(options.domain)
    allnet = ipnet('0.0.0.0/0')
    if domain_map.get(allnet, options.domain) != options.domain:
        print('Warning: Use of -d causes {} to override {}'.format(
              options.domain, domain_map[allnet]))
    domain_map[allnet] = options.domain

get_domain = domain_getter(domain_map)

# --- Set up tinydns authorized host data starting with the static info ---

dns = tinydata.AuthoritativeDNS()
warning = tinydata.Section()
warning.add(tinydata.Comment(' DO NOT EDIT! ALL CHANGES WILL BE LOST!'))

dns.read(*options.static)
warning.add(
    tinydata.Comment(
        ' This file is generated automatically from the following files.'),
    tinydata.Comment(' Edit them instead:')
    )
for file_name in options.static:
    warning.add(tinydata.Comment(file_name))
dns.prepend(warning)
dynamics = {}
mac_host_names = {}
leases = dhcpd.Leases(options.leases)
if options.macfile:
    for line in files.yield_lines(options.macfile):
        mac, host_name = line.split()
        mac = mac.strip()
        host_name.strip()
        try:
            lease = leases[mac]
        except KeyError:
            mac_host_names[host_name] = None
            continue
        domain_suffix, entry = make_alias_entry(lease, host_name)
        dynamics.setdefault(domain_suffix, []).append(entry)
        mac_host_names[host_name] = entry

for lease in leases.yield_unique():
    if lease.host_name is None or lease.host_name in mac_host_names:
        continue
    suffix, entry = make_alias_entry(lease)
    dynamics.setdefault(suffix, []).append(entry)

if dynamics:
    dhcp_section = tinydata.Section()
    dhcp_section.add(
        tinydata.Comment(
            ' {k} Everything below this line generated from DHCP {k}'.format(
                k='_' * 14)))
    dns.append(dhcp_section)
    for suffix, section in dynamics.items():
        w = tinydata.Section()
        w.add(tinydata.Comment(dhcp_header(suffix)), *section)
        dns.append(w)

if options.dry_run:
    print(dns)
else:
    dns.merge(options.root)
    # tinydata.make(options.root)
