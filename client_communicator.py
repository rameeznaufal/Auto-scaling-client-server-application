import json
import os
import signal
import sys


def signal_handler(sig, frame):
    print('\n\nYou pressed Ctrl+C ! Exiting...\n')
    sys.exit(0)


def interactive_client_communicator(client_fifo_file_name: str):
    try:
        while user_input := input("Enter your client command: "):
            os.system(f"echo '{user_input}' >> '{client_fifo_file_name}'")
    except EOFError:
        pass  # The use pressed CTRL+D
    return


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)

    fifo_file_name = json.load(open('client.conf', 'r'))['fifo_communication_file']
    interactive_client_communicator(fifo_file_name)