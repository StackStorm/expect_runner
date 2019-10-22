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
import tatsu

import paramiko

from st2common.runners.base import ActionRunner
from st2common.runners.base import get_metadata as get_runner_metadata
from st2common import log as logging
from st2common.util.config_loader import ContentPackConfigLoader
from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED
from st2common.constants.action import LIVEACTION_STATUS_FAILED
from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT

LOG = logging.getLogger(__name__)

HANDLER = 'ssh'

HANDLERS = {}

ENTRY_TIME = None

TIMEOUT = 60

SLEEP_TIMER = 0.2


class TimeoutError(Exception):
    pass


def _elapsed_time():
    return time.time() - ENTRY_TIME


def _check_timer():
    return _elapsed_time() <= TIMEOUT


def _remaining_time():
    return TIMEOUT - _elapsed_time()


def _expect_return(expect, output):
    return re.search(expect, output) is not None


def get_runner():
    return ExpectRunner(str(uuid.uuid4()))


def get_metadata():
    return get_runner_metadata('expect_runner')[0]


class ExpectRunner(ActionRunner):
    def _parse(self, output):
        model = tatsu.compile(self._grammar)
        parsed_output = model.parse(output, start=self._entry)
        LOG.info('Parsed output: %s', parsed_output)

        return parsed_output

    def _get_shell_output(self, cmds, default_expect):
        output = ''

        if not isinstance(cmds, list):
            raise ValueError("Expected list, got %s which is of type %s" % (cmds, type(cmds)))

        for cmd_tuple in cmds:
            LOG.debug("expect runner cmds: %s", cmd_tuple)
            if isinstance(cmd_tuple, list) and len(cmd_tuple) == 2:
                cmd = cmd_tuple.pop(0)
                expect = cmd_tuple.pop(0)
            elif isinstance(cmd_tuple, list) and len(cmd_tuple) == 1:
                cmd = cmd_tuple.pop(0)
                expect = default_expect
            elif isinstance(cmd_tuple, str):
                cmd = cmd_tuple
                expect = default_expect
            else:
                raise ValueError("Command error. Entry wasn't proper type (list or string)"
                                 " or list was of incorrect length. %s" % (cmd_tuple))

            LOG.debug("Dispatching command: %s, %s", cmd, expect)

            result = self._shell.send(cmd, expect)

            output += result if result else ''

        return output

    def _close_shell(self):
        LOG.debug('Terminating shell session')
        self._shell.terminate()

    def pre_run(self):
        super(ExpectRunner, self).pre_run()

        LOG.debug(
            'Entering ExpectRunner.PRE_run() for liveaction_id="%s"',
            self.liveaction_id
        )

        self._config = {
            'init_cmds': [],
            'default_expect': None
        }

        pack = self.get_pack_name()
        user = self.get_user()

        LOG.debug("Parsing config: %s, %s", pack, user)
        config_loader = ContentPackConfigLoader(pack_name=pack, user=user)
        config = config_loader.get_config()

        if config:
            LOG.debug("Loading pack config.")
            self._config['init_cmds'] = config.get('init_cmds', [])
            self._config['default_expect'] = config.get('default_expect', None)
        else:
            LOG.debug("No pack config found.")

        LOG.debug("Config: %s", self._config)

        self._username = self.runner_parameters.get('username', None)
        self._password = self.runner_parameters.get('password', None)
        self._host = self.runner_parameters.get('host', None)
        self._cmds = self.runner_parameters.get('cmds', None)
        self._entry = self.runner_parameters.get('entry', None)
        self._grammar = self.runner_parameters.get('grammar', None)
        self._timeout = self.runner_parameters.get('timeout', 60)

        global TIMEOUT
        TIMEOUT = self._timeout

    def run(self, action_parameters):
        LOG.debug(
            'Entering ExpectRunner.run() for liveaction_id="%s"',
            self.liveaction_id
        )

        global ENTRY_TIME
        ENTRY_TIME = time.time()

        try:
            handler = HANDLERS[HANDLER]

            self._shell = handler(
                self._host,
                self._username,
                self._password,
                self._timeout
            )

            init_output = self._get_shell_output(
                self._config['init_cmds'],
                self._config['default_expect']
            )
            LOG.debug("initial shell output: %s", output)
            output = self._get_shell_output(self._cmds, self._config['default_expect'])
            LOG.debug("shell output: %s", output)
            self._close_shell()

            if self._grammar and len(output) > 0:
                parsed_output = self._parse(output)
                result = {
                    'result': parsed_output,
                    'init_output': init_output,
                }
            else:
                result = {
                    'result': output,
                    'init_output': init_output,
                }

            result_status = LIVEACTION_STATUS_SUCCEEDED

        except (TimeoutError, socket.timeout) as e:
            LOG.debug("Timed out running action: %s", e)
            result_status = LIVEACTION_STATUS_TIMED_OUT
            error_message = dict(
                result=None,
                error='Action failed to complete in %s seconds' % TIMEOUT,
                exit_code=-9
            )
            result = error_message

        except Exception as e:
            LOG.debug("Hit exception running action: %s", e)
            result_status = LIVEACTION_STATUS_FAILED
            error_message = dict(error="%s" % e, result=None)
            result = error_message

        return (result_status, result, None)


class ConnectionHandler(object):
    def send(self, command, expect):
        pass


class SSHHandler(ConnectionHandler):
    def __init__(self, host, username, password, timeout):
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            host,
            username=username,
            password=password,
            timeout=timeout
        )
        self._shell = self._ssh.invoke_shell(term='vt100', width=200, height=200)
        self._shell.settimeout(_remaining_time())
        self._recv()

    def terminate(self):
        self._shell.close()

    def send(self, command, expect):
        self._shell.settimeout(_remaining_time())
        LOG.debug('Entering send: (%s, %s)', command, expect)

        if not command and not expect:
            raise ValueError("Expect and command cannot both be NoneType.")

        if command:
            self._shell.send(command + "\n")
        else:
            output = self._recv(expect, True)
            return output

        output = None

        if expect:
            output = self._recv(expect)

            output = output.replace('\\n', '\n').replace('\r', '').replace('\\r', '')
            LOG.debug('Output: %s', output)

        return output

    def _recv(self, expect=None, continue_return=False):
        LOG.debug("  receiving (%s, %s)", expect, continue_return)
        return_val = ''

        while not self._shell.recv_ready() and not self._shell.recv_stderr_ready() and _check_timer():
            LOG.debug("  waiting for shell to be ready...")
            if continue_return:
                LOG.debug("    sending newline")
                self._shell.send("\n")
            LOG.debug("    sleeping for %s", SLEEP_TIMER)
            time.sleep(SLEEP_TIMER)

        # If we have an error, return it
        # Note that since this is an error, we ignore the timeout timer when
        # trying to get the error message
        if self._shell.recv_stderr_ready():
            LOG.debug("Command encountered error")
            # Note: an excellent place for Python 3.8's "walrus" operator here
            error = 'notblank'
            while error != '':
                LOG.debug("  receiving 1024 characters from shell")
                error = self._shell.recv_stderr(1024)
                LOG.debug("  received %s bytes", len(error))
                if isinstance(error, bytes):
                    try:
                        error = error.decode('utf-8')
                    except UnicodeDecodeError:
                        error = str(error, errors='ignore')
                LOG.debug("  error from shell.recv_stderr(): %s", error)
                return_val += error if error else ''
            return return_val

        # While we still haven't timed out, keep checking for and grabbing
        # output from the command and comparing it to the expect
        # Break once we have what we expect, otherwise keep waiting until
        # timeout
        while _check_timer():
            # Double check that the command has output available for us
            if not self._shell.recv_ready():
                LOG.debug("  shell not ready, sleeping %s", SLEEP_TIMER)
                time.sleep(SLEEP_TIMER)
                continue
            LOG.debug("  receiving 1024 characters from shell")
            output = self._shell.recv(1024)
            LOG.debug("  received %s bytes", len(output))
            if isinstance(output, bytes):
                try:
                    output = output.decode('utf-8')
                except UnicodeDecodeError:
                    output = str(output, errors='ignore')
            LOG.debug("  output from shell.recv(): %s", output)
            return_val += output if output else ''

            LOG.debug("  expect: %s", expect)
            LOG.debug("  return val: %s", return_val)
            if (expect and _expect_return(expect, return_val)) or not expect:
                LOG.debug("    expect matched return value")
                break

            if continue_return:
                LOG.debug("  sending newline")
                self._shell.send("\n")

        if not _check_timer():
            raise TimeoutError("Reached timeout (%s seconds). Recieved: %s" % (TIMEOUT, return_val))

        return return_val

HANDLERS['ssh'] = SSHHandler
