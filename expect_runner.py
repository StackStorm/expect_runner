# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import uuid
import time
import socket
import re
import json
import grako

import paramiko

from st2common.runners import ActionRunner
from st2common import log as logging
from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED
from st2common.constants.action import LIVEACTION_STATUS_FAILED
from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT

LOG = logging.getLogger(__name__)

HANDLER = 'ssh'

HANDLERS = {}

ENTRY_TIME = None

TIMEOUT = 60

SLEEP_TIMER = 0.2


# TODO: Consider moving to st2common.
class TimeoutError(Exception):
    pass


def _check_timer():
    elapsed_time = _elapsed_time()

    return bool(elapsed_time <= TIMEOUT)


def _elapsed_time():
    elapsed_time = time.time() - ENTRY_TIME

    return elapsed_time


def _remaining_time():
    elapsed_time = _elapsed_time()
    remaining_time = TIMEOUT - elapsed_time

    return remaining_time


def _expect_return(expect, output):
    search_result = bool(re.search(expect, output))

    return search_result


def get_runner():
    return ExpectRunner(str(uuid.uuid4()))


class ExpectRunner(ActionRunner):
    def __init__(self, runner_id):
        super(ExpectRunner, self).__init__(runner_id=runner_id)

    def _parse_grako(self, output):
        parser = grako.genmodel("output_parser", self._grammar)
        parsed_output = parser.parse(output, self._entry)
        LOG.info('Parsed output: %s', parsed_output)

        return parsed_output

    def _get_shell_output(self):
        output = ''
        for command in self._cmd:
            cmd = command[0]
            expect = command[1]
            LOG.debug("Dispatching command: %s, %s", cmd, expect)

            output += self._shell.send(cmd, expect)

        return output

    def _init_shell(self):
        LOG.debug('Entering _init_shell')

        self._shell.send('term len 0\n', r'>')

    def pre_run(self):
        super(ExpectRunner, self).pre_run()

        LOG.debug('Entering ExpectRunner.PRE_run() for liveaction_id="%s"',
                  self.liveaction_id)
        self._username = self.runner_parameters.get('username', None)
        self._password = self.runner_parameters.get('password', None)
        self._host = self.runner_parameters.get('host', None)
        self._cmd = self.runner_parameters.get('cmd', None)
        self._entry = self.runner_parameters.get('entry', None)
        self._grammar = self.runner_parameters.get('grammar', None)
        self._timeout = self.runner_parameters.get('timeout', 60)

        global TIMEOUT
        TIMEOUT = self._timeout

    def run(self, action_parameters):
        LOG.debug('Entering ExpectRunner.PRE_run() for liveaction_id="%s"',
                  self.liveaction_id)

        global ENTRY_TIME
        ENTRY_TIME = time.time()

        try:
            handler = HANDLERS[HANDLER]

            self._shell = handler(
                self._host,
                self._username,
                self._password,
                self._timeout)
            self._init_shell()

            output = self._get_shell_output()
            parsed_output = self._parse_grako(output)

            result = json.dumps(parsed_output)
            result_status = LIVEACTION_STATUS_SUCCEEDED

        except Exception as error:
            LOG.debug("Hit exception running action: %s", error)
            result_status = LIVEACTION_STATUS_FAILED

            if error is TimeoutError or error is socket.timeout:
                LOG.debug("Exeption was timeout.")
                error_message = dict(error="%s" % error)
                result_status = LIVEACTION_STATUS_TIMED_OUT

            error_message = dict(error="%s" % error)

            result = json.dumps(error_message)

        return (result_status, result, None)


class ConnectionHandler(object):
    def send(self, command, expect):
        pass


class SSHHandler(ConnectionHandler):
    def __init__(self, host, username, password, timeout):
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            host, username=username,
            password=password,
            timeout=timeout
        )
        self._shell = self._ssh.invoke_shell()
        self._shell.settimeout(_remaining_time())

        while not self._shell.recv_ready() and _check_timer():
            time.sleep(SLEEP_TIMER)

        self._recv()

        if not _check_timer():
            raise TimeoutError

        LOG.debug("Captured init message: %s", self._recv())

        if not _check_timer():
            raise TimeoutError

    def send(self, command, expect):
        self._shell.settimeout(_remaining_time())
        LOG.debug('Entering _get_ssh_output')

        self._shell.send(command + "\n")

        output = self._recv(expect)

        LOG.debug('Output: %s', output)
        output = output.replace('\\n', '\n').replace('\\r', '')

        return output

    def _recv(self, expect=None):
        return_val = ''

        while self._shell.recv_ready() and _check_timer():
            if not self._shell.recv_ready():
                time.sleep(SLEEP_TIMER)
                continue

            return_val += self._shell.recv(1024)

            if expect is not None and _expect_return(expect, return_val):
                break

        if not _check_timer():
            raise TimeoutError

        return return_val

HANDLERS['ssh'] = SSHHandler
