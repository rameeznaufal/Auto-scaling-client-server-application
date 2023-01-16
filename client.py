import fcntl
import json
import logging
import os
import random
import signal
import socket
import struct
import sys
import time
from typing import Dict

from client_common_services import ClientFIFO


def make_fd_non_blocking(file_fd):
    """
    make file_fd a non-blocking file descriptor
    """
    fl = fcntl.fcntl(file_fd, fcntl.F_GETFL)
    fcntl.fcntl(file_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


def client_init(client_conf: dict):
    logging.basicConfig(
        level=eval(f'logging.{client_conf["logging_level"]}'),
        stream=(open(client_conf['logging_file'], 'a') if client_conf['logging_file'] != '/dev/stdout' else sys.stdout),
        format='%(asctime)s :: %(levelname)s :: %(lineno)s :: %(funcName)s :: %(message)s'
    )

    problem_with_fifo = False
    if client_conf['fifo_communication_file'] != '/dev/stdin':
        try:
            os.mkfifo(client_conf['fifo_communication_file'])
            logging.info(f'File used for communication = "{client_conf["fifo_communication_file"]}"')

            client_conf['fifo_communication_file_obj'] = open(client_conf['fifo_communication_file'])
            logging.info('FIFO file successfully opened :)')
        except OSError as e:
            logging.warning(f'Failed to create FIFO: {e}')
            problem_with_fifo = True
            sys.exit(1)

    if problem_with_fifo or client_conf['fifo_communication_file'] == '/dev/stdin':
        client_conf['fifo_communication_file'] = '/dev/stdin'
        client_conf['fifo_communication_file_obj'] = sys.stdin
        logging.info(f'File used for communication = "/dev/stdin"')

    make_fd_non_blocking(client_conf['fifo_communication_file_obj'].fileno())
    logging.debug('client_init() FINISHED :)')
    return


def start_sending_requests(client_conf, message_conf) -> None:
    logging.debug('start_sending_requests(...) STARTED :)')
    client_conf['server_address_port'] = list()
    if client_conf['server_ip'].lower() != 'none':
        client_conf['server_address_port'].append(
            (client_conf['server_ip'], client_conf['server_port'])
        )

    udp_client_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)


    udp_client_socket.setblocking(False)
    client_fifo: ClientFIFO = ClientFIFO(client_conf['fifo_communication_file_obj'], 21001)

    server_to_send_req_idx = -1
    total_requests_sent = 0
    total_replies_received = 0
    avg_throughtput_req_count_X = 50
    n_minus_X_req_time = time.time_ns()
    
    while True:
        if client_conf['req_load'] not in ('low', 'mid', 'high', 'custom'):
            logging.critical('Wrong value stored in "client_conf[\'req_load\']"')
        next_sleep_time = time.time() + client_conf[f'load_request_time_period_seconds_{client_conf["req_load"]}']

        client_fifo.check_fifo(client_conf)

        if len(client_conf['server_address_port']) == 0:
            logging.debug('Total servers = len(client_conf[\'server_address_port\']) = 0')
        else:
            if len(client_conf['server_address_port']) != 0:
                server_to_send_req_idx = (server_to_send_req_idx + 1) % len(client_conf['server_address_port'])

            req_int = random.randint(client_conf['req_num_low'], client_conf['req_num_high'])

            # Format: big-endian and 4 bytes (unsigned int)
            req_bytes_to_send = struct.pack(">I", req_int)  # max value can be "2**32 - 1"
            logging.debug(f'Query:')
            logging.debug(f'    req_int           = {req_int}')
            logging.debug(f'    req_bytes_to_send = {req_bytes_to_send}')

            logging.debug(f"client_conf['server_address_port'][server_to_send_req_idx] = "
                          f"{client_conf['server_address_port'][server_to_send_req_idx]}")
            udp_client_socket.sendto(req_bytes_to_send, client_conf['server_address_port'][server_to_send_req_idx])
            total_requests_sent += 1

        # Receive all server replies without blocking
        # Format: big-endian and 8 bytes (unsigned long long)
        try:
            while True:
                req_reply_bytes, server_addr = udp_client_socket.recvfrom(8)
                logging.debug(f'Response of server_addr = {server_addr}')
                logging.debug(f'    req_reply_bytes = {req_reply_bytes}')
                req_reply_int = int.from_bytes(req_reply_bytes, 'big')
                logging.debug(f'    req_reply_int   = {req_reply_int}')
                total_replies_received += 1
                if total_replies_received % avg_throughtput_req_count_X == 0:
                    logging.info(f'Server Request THROUGHPUT = '
                                 f'{(avg_throughtput_req_count_X * 1000000000) / (time.time_ns() - n_minus_X_req_time):.9f} / second')
                    n_minus_X_req_time = time.time_ns()
        # 1 / (((time.time_ns() - n_minus_X_req_time) / 1000000000) / avg_throughtput_req_count_X)
        except BlockingIOError:
            pass  # nothing to receive
        except Exception as e:
            logging.debug(f'type(e) = {type(e)}')
            logging.debug(f'e = {e}')

        logging.info(f'STATS: total_requests_sent = {total_requests_sent} | total_replies_received = {total_replies_received}')
        logging.info(f'STATS: PENDING replies = {total_requests_sent - total_replies_received}')
        logging.info(f"STATS: client_conf['server_address_port'] = {client_conf['server_address_port']}")
        if time.time() < next_sleep_time:
            time.sleep(next_sleep_time - time.time())
    logging.debug('start_sending_requests(...) ENDED - this will never execute')
    pass


GLOBAL_CLIENT_CONF: Dict = dict()


def signal_handler(sig, frame):
    print('\n\nYou pressed Ctrl+C ! Exiting...\n')
    if 'fifo_communication_file_obj' in GLOBAL_CLIENT_CONF:
        GLOBAL_CLIENT_CONF['fifo_communication_file_obj'].close()
    if GLOBAL_CLIENT_CONF['fifo_communication_file'] != '/dev/stdin':
        os.remove(GLOBAL_CLIENT_CONF['fifo_communication_file'])
        if os.path.exists(GLOBAL_CLIENT_CONF['fifo_communication_file']):
            logging.critical(
                'Due to unknown reason, FIFO file was not deleted with "os.remove(...)". Now using "rm -f ..."'
            )
            os.system(f'rm -f "{GLOBAL_CLIENT_CONF["fifo_communication_file"]}"')
    logging.debug(f'Successfully deleted "{GLOBAL_CLIENT_CONF["fifo_communication_file"]}"')
    logging.debug("")
    logging.debug("")
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)

    with open('message.conf') as f:
        MESSAGE_CONF = json.load(f)
    with open('client.conf') as f:
        CLIENT_CONF = json.load(f)

    GLOBAL_CLIENT_CONF: Dict = CLIENT_CONF
    client_init(CLIENT_CONF)

    start_sending_requests(CLIENT_CONF, MESSAGE_CONF)