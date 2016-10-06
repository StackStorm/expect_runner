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
import re
import json
import grako

import paramiko

from st2common.runners import ActionRunner
from st2common import log as logging
from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED
# from st2common.constants.action import LIVEACTION_STATUS_FAILED
# from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT

LOG = logging.getLogger(__name__)


def get_runner():
    return ExpectRunner(str(uuid.uuid4()))


def _parse_grako(output, grammar, entry):
    parser = grako.genmodel("output_parser", grammar)
    parsed_output = parser.parse(output, entry)
    LOG.info('Parsed output: %s', parsed_output)

    return parsed_output


def _get_ssh_output(host, username, password, commands, expect):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=username, password=password)
    shell = ssh.invoke_shell()
    shell.send('term len 0\n')
    shell.recv(1024)
    ret = []
    count = 0
    for command in commands:
        shell.send(command + "\n")
        return_val = ""
        expect_search = []
        while len(expect_search) == 0:
            time.sleep(1)
            return_val += shell.recv(1024)
            expect_search = re.findall(expect[count], return_val)
        count += 1
        ret.append(return_val)
    LOG.info('Output: %s', ret)
    ret = ''.join(ret).replace('\\n', '\n').replace('\\r', '')

    return ret


class ExpectRunner(ActionRunner):
    def __init__(self, runner_id):
        super(ExpectRunner, self).__init__(runner_id=runner_id)
        self._timeout = 60

    def pre_run(self):
        super(ExpectRunner, self).pre_run()

        LOG.debug('Entering ExpectRunner.PRE_run() for liveaction_id="%s"',
                  self.liveaction_id)
        self._cmd = self.runner_parameters.get('cmd', None)
        self._expect = self.runner_parameters.get('expect', None)
        self._entry = self.runner_parameters.get('entry', None)
        self._grammar = self.runner_parameters.get('grammar', None)
        self._username = self.runner_parameters.get('username', None)
        self._password = self.runner_parameters.get('password', None)
        self._host = self.runner_parameters.get('host', None)

    def run(self, action_parameters):
        cmd = action_parameters.get('cmd', self._cmd)
        expect = action_parameters.get('expect', self._expect)
        entry = action_parameters.get('entry', self._entry)
        grammar = action_parameters.get('grammar', self._grammar)
        username = action_parameters.get('username', self._username)
        password = action_parameters.get('password', self._password)
        host = action_parameters.get('host', self._host)
        output = _get_ssh_output(
            host,
            username,
            password,
            cmd,
            expect
        )

        result = json.dumps(_parse_grako(output, grammar, entry))
        status = LIVEACTION_STATUS_SUCCEEDED

        return (status, result, None)
