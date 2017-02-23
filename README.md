## Installation

 - Minimum requirements: StackStorm 2.2
 - Clone this github repo, e.g. `git clone https://github.com/StackStorm/expect_runner`
 - Copy the content to `/opt/stackstorm/runners`: `cp -r expect_runner /opt/stackstorm/packs`
 - Install the python libraries:
 
 ```
 sudo su -
 source /opt/stackstorm/st2/bin/activate
 pip install -r /opt/stackstorm/runners/expect_runner/requirements.txt
 deactivate
 ```
 
 - Register the runner: `sudo st2ctl reload --register-runners`
 
 - Check that the runner is registered: `st2 runner get expect`
