#
# Copyright (c) 2015 Autodesk Inc.
# All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import logging
import time
import json
import os

from jinja2 import Environment, FileSystemLoader, Template
from ochopod.bindings.ec2.marathon import Pod
from ochopod.core.utils import shell
from ochopod.models.piped import Actor as Piped
from ochopod.models.reactive import Actor as Reactive
from os.path import join, dirname

logger = logging.getLogger('ochopod')


if __name__ == '__main__':

    class Model(Reactive):

        damper = 30.0

        probe_every = 30.0

        sequential = True

        def get_replset(self):
            code, lines = shell("echo 'JSON.stringify(rs.status())' | mongo --host localhost --port 27018 --quiet")
            assert code == 0, 'failed to connect to local pod (is it dead ?)'
            return json.loads(' '.join(lines))

        def probe(self, cluster):
            #
            # - Issue the rs.status() request to get the health of the overall replicaSet
            # - The goal is to ensure that the replicaSet has
            #   - One primary (stateStr == 'PRIMARY')
            #   - All pods added to the replicaSet ( cluster.size - 1 secondaries )
            #
            primary = None
            secondaries = []

            props = self.get_replset()
            if 'members' not in props.keys():
                # we need to performs rs.initiate()
                rs_name = os.getenv('REPLSET_NAME', 'rs0')
                rs_config_doc = {'_id': rs_name, 'members': []}
                for key, pod in cluster.pods.items():
                    rs_config_doc['members'].append({
                        '_id': pod['seq'],
                        'host': "%s:%d" % (pod['ip'], pod['ports']['27018'])
                    })
                # configure
                jsonstr = json.dumps(rs_config_doc)
                code, _ = shell("echo 'rs.initiate(%s)' | mongo --host localhost --port 27018 --quiet" % jsonstr)
                assert code == 0, 'Unable to do rs.initiate(%s)' % jsonstr
                # get replset info
                props = self.get_replset()
                members = props['members']
            else:
                members = props['members']
            assert len(members) == cluster.size, 'All members not present in the replicaSet'

            # get configuration and get status
            for key, pod in cluster.pods.items():
                # find pod in `members` - list of dicts
                pod_mongostr = "%s:%d" % (pod['ip'], pod['ports']['27018'])
                member = (item for item in members if item["name"] == pod_mongostr).next()
                assert member, 'unable to find pod #%d in replicaSet' % (pod['seq'])

                state = member['stateStr']
                assert state in ['PRIMARY', 'SECONDARY'], 'pod #%d -> <%s>' % (pod['seq'], member['stateStr'])

                if state == 'PRIMARY':
                    primary = member
                elif state == 'SECONDARY':
                    secondaries.append(member)
            assert primary, 'no primary found ?'
            assert len(secondaries) == cluster.size - 1, '1+ secondaries not synced'
            # respond with the members json response
            return json.dumps(members)

    class Strategy(Piped):

        pid = None
        since = 0.0

        pipe_subprocess = True
        checks = 3

        def sanity_check(self, pid):
            #
            # - simply use the provided process ID to start counting time
            # - this is a cheap way to measure the sub-process up-time
            #
            now = time.time()
            if pid != self.pid:
                self.pid = pid
                self.since = now

            lapse = (now - self.since) / 3600.0

            return {'uptime': '%.2f hours (pid %s)' % (lapse, pid)}

        def configure(self, cluster):
            #
            # - render the mongod config template
            #
            env = Environment(loader=FileSystemLoader(join(dirname(__file__), 'templates')))
            template = env.get_template('mongod.yaml')
            mapping = \
                {
                    'logVerbosityLevel': os.getenv('LOG_VERBOSITY', '0'),
                    'slowMs': os.getenv('SLOW_MS', '1000'),
                    'profilingMode': os.getenv('PROFILING_MODE', 'off'),
                    'port': '27018',
                    'dbPath': os.getenv('MESOS_SANDBOX', '/var/lib/mongodb'),
                    'engine': os.getenv('ENGINE', 'wiredTiger'),
                    'wiredTiger': {
                        'engineConfig': {
                            'cacheSizeGB': os.getenv('CACHE_SIZE_GB', '2'),
                            'statisticsLogDelaySecs': os.getenv('STATS_LOG_DELAY_SECS', '0'),
                            'journalCompressor': os.getenv('JOURNAL_COMPRESSOR', 'snappy'),
                            'directoryForIndexes': os.getenv('DIRECTORY_FOR_INDEXES', 'false')
                        },
                        'collectionConfig': {
                            'blockCompressor': os.getenv('BLOCK_COMPRESSOR', 'zlib')
                        },
                        'indexConfig': {
                            'prefixCompression': os.getenv('PREFIX_COMPRESSION', 'true')
                        }
                    },
                    'replSetName': os.getenv('REPLSET_NAME', 'rs0')
                }

            with open('/etc/mongod.yaml', 'wb') as f:
                f.write(template.render(mapping))

            return 'mongod --config /etc/mongod.yaml', {}

    Pod().boot(Strategy, model=Model)
