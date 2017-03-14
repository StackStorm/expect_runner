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

from st2common.runners.base import ActionRunner
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


class ExpectRunner(ActionRunner):
    def _parse_grako(self, output):
        parser = grako.genmodel("output_parser", self._grammar)
        parsed_output = parser.parse(output, self._entry)
        LOG.info('Parsed output: %s', parsed_output)

        return parsed_output

    def _get_shell_output(self, cmds, default_expect):
        output = ''

        if not isinstance(cmds, list):
            raise ValueError("Expected list, got %s which is of type %s" % (cmds, type(cmds)))

        for cmd_tuple in cmds:
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
            output = self._get_shell_output(self._cmds, self._config['default_expect'])
            self._close_shell()

            if self._grammar and len(output) > 0:
                parsed_output = self._parse_grako(output)
                result = json.dumps({'result': parsed_output,
                                     'init_output': init_output})
            else:
                result = json.dumps({'result': output,
                                     'init_output': init_output})

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
        self._shell = self._ssh.invoke_shell()
        self._shell.settimeout(_remaining_time())
        self._recv()

    def terminate(self):
        self._shell.close()

    def send(self, command, expect):
        self._shell.settimeout(_remaining_time())
        LOG.debug('Entering send')

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

            LOG.debug('Output: %s', output)
            output = output.replace('\\n', '\n').replace('\\r', '')

        return output

    def _recv(self, expect=None, continue_return=False):
        return_val = ''

        while not self._shell.recv_ready() and _check_timer():
            if continue_return:
                self._shell.send("\n")
            time.sleep(SLEEP_TIMER)

        while _check_timer():
            if not self._shell.recv_ready():
                time.sleep(SLEEP_TIMER)
                continue
            output = self._shell.recv(1024).decode('UTF-8')
            return_val += output if output else u''

            if (expect and _expect_return(expect, return_val)) or not expect:
                break

            if continue_return:
                self._shell.send("\n")

        if not _check_timer():
            raise TimeoutError("Reached timeout (%s seconds). Recieved: %s" % (TIMEOUT, return_val))

        return return_val

HANDLERS['ssh'] = SSHHandler
