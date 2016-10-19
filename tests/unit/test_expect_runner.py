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

import mock
import json
import expect_runner

from st2actions.container import service
from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED, LIVEACTION_STATUS_FAILED
from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT
from st2tests.base import RunnerTestCase
from st2tests.base import CleanDbTestCase

RUNNER_PARAMETERS = dict(
    cmds=[
        'one happy command'
    ],
    grammar="""@@whitespace :: /[\t ]+/
    entry = /(?:.|\n)+/;
    """,
    entry='entry',
    host='10.4.2.1',
    username='emma',
    password='stone',
    timeout=60
)

MULTIPLE_COMMANDS = [
    'one happy command',
    'two happy commands'
]

MOCK_COMPLEX_GRAMMAR = """@@whitespace :: /[\t ]+/
number = /[0-9]+/;
string = ?/[a-zA-Z0-9\-\_\=\.\:'\/\+]+/?;
name = (string string);
catch_all = /.*\n/;
item = (number name:name birthday_month:string age:number [/\n/]);
entry = { entries:item | catch_all }+;
"""

MOCK_OUTPUT = """This is example output of a shell. It contains entries one
    can parse and also this text that you can choose to ignore. The list is
    of random actors. The age/birthday info is bogus...
    #   Name                 Birthday Month   Age
    1   George Clooney       Januaray         21
    2   Emma Stone           December         22
    3   Leonardo Dicaprio    July             14
    4   Margot Robbie        September        76
    5   Kevin Bacon          May              194

    SSH@MyHappyShell>
    SSH@MyHappyShell#
    """

MOCK_JSON_ENTRIES = """{"entries": [{"name": ["George", "Clooney"],
"birthday_month": "Januaray", "age": "21"}, {"name": ["Emma", "Stone"],
"birthday_month": "December", "age": "22"}, {"name": ["Leonardo", "Dicaprio"],
"birthday_month": "July", "age": "14"}, {"name": ["Margot", "Robbie"],
"birthday_month": "September", "age": "76"}, {"name": ["Kevin", "Bacon"],
"birthday_month": "May", "age": "194"}]}"""

MOCK_BROKEN_GRAMMAR = "entry = {/.*/}"

MockParimiko = mock.MagicMock()
MockParimiko.SSHClient().invoke_shell().recv_ready.return_value = True
MockParimiko.SSHClient().invoke_shell().recv.return_value = MOCK_OUTPUT

@mock.patch('expect_runner.paramiko', MockParimiko)
class ExpectRunnerTestCase(RunnerTestCase, CleanDbTestCase):
    register_packs = True
    register_pack_configs = True

    def test_runner_creation(self):
        runner = expect_runner.get_runner()
        self.assertTrue(runner is not None, 'Creation failed. No instance.')
        self.assertEqual(type(runner), expect_runner.ExpectRunner, 'Creation failed. No instance.')

    def test_grako_parser(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = dict(RUNNER_PARAMETERS)
        runner.runner_parameters['grammar'] = MOCK_COMPLEX_GRAMMAR
        runner.container_service = service.RunnerContainerService()
        runner.pre_run()
        (status, output, _) = runner.run(None)

        output = json.loads(output)
        mock_json_entries = json.loads(MOCK_JSON_ENTRIES)

        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output, mock_json_entries)

    def test_expect_timeout(self, *args):
        timeout = 0
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.container_service = service.RunnerContainerService()
        runner.runner_parameters = dict(RUNNER_PARAMETERS)
        runner.runner_parameters['timeout'] = timeout
        runner.pre_run()
        (status, output, _) = runner.run(runner.action)
        self.assertEqual(status, LIVEACTION_STATUS_TIMED_OUT)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)
        self.assertEqual(output['error'], 'Action failed to complete in 0 seconds')
        self.assertEqual(output['exit_code'], -9)

    def test_expect_succeeded(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = RUNNER_PARAMETERS
        runner.container_service = service.RunnerContainerService()
        runner.pre_run()
        (status, output, _) = runner.run(None)
        output = json.loads(output)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output, MOCK_OUTPUT)

    def test_expect_failed(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = dict(RUNNER_PARAMETERS)
        runner.runner_parameters['grammar'] = MOCK_BROKEN_GRAMMAR
        runner.container_service = service.RunnerContainerService()
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)

    def test_multiple_cmds(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = RUNNER_PARAMETERS
        runner.runner_parameters['cmds'] = MULTIPLE_COMMANDS
        runner.container_service = service.RunnerContainerService()
        runner.pre_run()
        (status, output, _) = runner.run(None)
        output = json.loads(output)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output, MOCK_OUTPUT*2)

    def test_paramiko_interface(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = RUNNER_PARAMETERS
        runner.container_service = service.RunnerContainerService()
        runner.pre_run()
        (status, output, _) = runner.run(None)

        ssh_client = MockParimiko.SSHClient()
        shell = ssh_client.invoke_shell()

        MockParimiko.SSHClient.assert_called()

        ssh_client.set_missing_host_key_policy.assert_called_with(
            MockParimiko.AutoAddPolicy()
        )
        ssh_client.connect.assert_called_with(
            RUNNER_PARAMETERS['host'],
            username=RUNNER_PARAMETERS['username'],
            password=RUNNER_PARAMETERS['password'],
            timeout=RUNNER_PARAMETERS['timeout']
            )
        ssh_client.invoke_shell.assert_called()

        shell.settimeout.assert_called()
        shell.recv.assert_called_with(1024)

    def _get_mock_action_obj(self):
        """
        Return mock action object.
        """
        action = mock.Mock()
        action.pack = 'expect_test_pack'

        return action
