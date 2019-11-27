# -*- coding: utf-8 -*-
# Copyright 2019 Extreme Networks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import copy

import six
import mock

from st2common.constants.action import LIVEACTION_STATUS_SUCCEEDED, LIVEACTION_STATUS_FAILED
from st2common.constants.action import LIVEACTION_STATUS_TIMED_OUT
from st2tests.base import RunnerTestCase

from expect_runner import expect_runner


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
    ['two happy commands', '#']
]

MULTIPLE_COMMANDS_DICT_ITEMS = [
    {'cmd': 'one happy command'},
    {'cmd': 'two happy command', 'expect': '#'},
]
NONE_EXPECT = [
    ['one happy command', None]
]

NONE_COMMANDS = [
    [None, '#']
]

NONE_EXPECT_COMMANDS = [
    [None, None]
]

EXPECT_NOT_IN_OUTPUT = [
    '{'
]

BROKEN_COMMANDS = "very bad command that isn't a list"

MOCK_COMPLEX_GRAMMAR = r"""@@whitespace :: /[\t ]+/
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

MOCK_UNICODE_OUTPUT_STR = (
    """
    This is example output of a shell. It contains entries one
    can parse and also this text that you can choose to ignore. The list is
    of random actors. The age/birthday info is bogus...
    #   Name                 Birthday Month   Age
    1   George Clooney       Januaray         21
    2   Emma Stone           December         22
    3   Leonardo Dicaprio    July             14
    4   Margot Robbie        September        76
    5   Kevin Bacon          May              194
    œ
    SSH@MyHappyShell>
    SSH@MyHappyShell#
    """
)

if six.PY2:
    MOCK_UNICODE_OUTPUT = MOCK_UNICODE_OUTPUT_STR.decode('utf-8')
else:
    MOCK_UNICODE_OUTPUT = MOCK_UNICODE_OUTPUT_STR

MOCK_UNICODE_OUTPUT_WITH_FAKE_BYTE = MOCK_UNICODE_OUTPUT_STR + chr(255)

MOCK_JSON_ENTRIES = """{"entries": [{"name": ["George", "Clooney"],
"birthday_month": "Januaray", "age": "21"}, {"name": ["Emma", "Stone"],
"birthday_month": "December", "age": "22"}, {"name": ["Leonardo", "Dicaprio"],
"birthday_month": "July", "age": "14"}, {"name": ["Margot", "Robbie"],
"birthday_month": "September", "age": "76"}, {"name": ["Kevin", "Bacon"],
"birthday_month": "May", "age": "194"}]}"""

MOCK_BROKEN_GRAMMAR = "entry = {/.*/}"

MockParimiko = mock.MagicMock()
MockParimiko.SSHClient().invoke_shell().recv_ready.side_effect = \
    lambda: (MockParimiko.SSHClient().invoke_shell().recv_ready.call_count % 2) == 0
MockParimiko.SSHClient().invoke_shell().recv_stderr_ready.side_effect = \
    mock.Mock(return_value=False)
MockParimiko.SSHClient().invoke_shell().recv.return_value = MOCK_OUTPUT


MOCK_CONFIG = {
    'init_cmds': ['enable'],
    'default_expect': '#'
}

MockContentPackConfigLoader = mock.MagicMock()
MockContentPackConfigLoader().get_config().return_value = MOCK_CONFIG

MockNoContentPackConfigLoader = mock.MagicMock()
MockNoContentPackConfigLoader().get_config().return_value = None


@mock.patch.object(
    expect_runner.ContentPackConfigLoader,
    'get_config',
    mock.MagicMock(return_value=MOCK_CONFIG))
@mock.patch('expect_runner.expect_runner.paramiko', MockParimiko)
@mock.patch('expect_runner.expect_runner.SLEEP_TIMER', 0.05)  # Decrease sleep to speed up tests
class ExpectRunnerTestCase(RunnerTestCase):
    maxDiff = None

    def test_runner_creation(self):
        runner = expect_runner.get_runner()
        self.assertTrue(runner is not None, 'Creation failed. No instance.')
        self.assertEqual(type(runner), expect_runner.ExpectRunner, 'Creation failed. No instance.')

    def test_grako_parser(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['grammar'] = MOCK_COMPLEX_GRAMMAR
        runner.pre_run()
        (status, output, _) = runner.run(None)

        mock_json_entries = json.loads(MOCK_JSON_ENTRIES)

        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], mock_json_entries)

    @mock.patch('expect_runner.expect_runner.SLEEP_TIMER', 1)
    def test_expect_timeout(self, *args):
        timeout = 0
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['timeout'] = timeout
        runner.pre_run()
        (status, output, _) = runner.run(runner.action)
        self.assertEqual(status, LIVEACTION_STATUS_TIMED_OUT)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)
        self.assertEqual(output['error'], 'Action failed to complete in 0 seconds')
        self.assertEqual(output['exit_code'], -9)

    @mock.patch('expect_runner.expect_runner.SLEEP_TIMER', 1)
    def test_expect_timeout_on_expect_fail(self, *args):
        timeout = 0.01
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['expects'] = EXPECT_NOT_IN_OUTPUT
        runner.runner_parameters['timeout'] = timeout
        runner.pre_run()
        (status, output, _) = runner.run(runner.action)
        self.assertEqual(status, LIVEACTION_STATUS_TIMED_OUT)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)
        self.assertEqual(output['error'], 'Action failed to complete in 0.01 seconds')
        self.assertEqual(output['exit_code'], -9)

    def test_expect_succeeded(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = RUNNER_PARAMETERS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], MOCK_OUTPUT)

    def test_expect_failed(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['grammar'] = MOCK_BROKEN_GRAMMAR
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], None)

    def test_multiple_cmds_as_array_of_arays(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = MULTIPLE_COMMANDS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], MOCK_OUTPUT * 2)

    def test_multiple_cmds_as_array_of_dicts(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = MULTIPLE_COMMANDS_DICT_ITEMS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], MOCK_OUTPUT * 2)

    def test_paramiko_interface(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = RUNNER_PARAMETERS
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

    def test_cmds_not_list(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = BROKEN_COMMANDS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertEqual(
            output['error'],
            "Expected list, got %s which is of type str" % (BROKEN_COMMANDS)
        )

    @mock.patch.object(
        expect_runner.ContentPackConfigLoader,
        'get_config',
        mock.MagicMock(return_value=None))
    def test_no_grammar_with_no_config(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['grammar'] = None
        runner.pre_run()
        (status, output, _) = runner.run(None)
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], MOCK_OUTPUT)

    def test_none_expect(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = NONE_EXPECT
        runner.pre_run()
        (status, output, _) = runner.run(None)
        output = output
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], '')

    def test_none_cmd(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = NONE_COMMANDS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        output = output
        self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
        self.assertTrue(output is not None)
        self.assertEqual(output['result'], MOCK_OUTPUT)

    def test_none_cmd_expect(self):
        runner = expect_runner.get_runner()
        runner.action = self._get_mock_action_obj()
        runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
        runner.runner_parameters['cmds'] = NONE_EXPECT_COMMANDS
        runner.pre_run()
        (status, output, _) = runner.run(None)
        output = output
        self.assertEqual(status, LIVEACTION_STATUS_FAILED)
        self.assertTrue(output is not None)
        self.assertEqual(output['error'], 'Expect and command cannot both be NoneType.')

    def test_unicode_response(self):
        MockUnicodeParimiko = mock.MagicMock()
        MockUnicodeParimiko.SSHClient().invoke_shell().recv_ready.side_effect = \
            lambda: (MockParimiko.SSHClient().invoke_shell().recv_ready.call_count % 2) == 0
        MockUnicodeParimiko.SSHClient().invoke_shell().recv_stderr_ready.side_effect = \
            mock.Mock(return_value=False)
        MockUnicodeParimiko.SSHClient().invoke_shell().recv.return_value = MOCK_UNICODE_OUTPUT

        with mock.patch('expect_runner.expect_runner.paramiko', MockUnicodeParimiko):
            runner = expect_runner.get_runner()
            runner.action = self._get_mock_action_obj()
            runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
            runner.pre_run()
            (status, output, _) = runner.run(None)
            output = output
            self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
            self.assertTrue(output is not None)
            self.assertEqual(output['result'], MOCK_UNICODE_OUTPUT)

        MockUnicodeParimiko.SSHClient().invoke_shell().recv.return_value = \
            MOCK_UNICODE_OUTPUT_WITH_FAKE_BYTE

        with mock.patch('expect_runner.expect_runner.paramiko', MockUnicodeParimiko):
            runner = expect_runner.get_runner()
            runner.action = self._get_mock_action_obj()
            runner.runner_parameters = copy.deepcopy(RUNNER_PARAMETERS)
            runner.pre_run()
            (status, output, _) = runner.run(None)
            output = output
            self.assertEqual(status, LIVEACTION_STATUS_SUCCEEDED)
            self.assertTrue(output is not None)

            if six.PY2:
                self.assertEqual(output['result'], MOCK_UNICODE_OUTPUT)
            else:
                self.assertEqual(output['result'], MOCK_UNICODE_OUTPUT_WITH_FAKE_BYTE)
