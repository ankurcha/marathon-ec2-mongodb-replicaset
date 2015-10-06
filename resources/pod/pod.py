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

        @staticmethod
        def rs_status():
            """
            Executes rs.status() against the localhost mongod
            """
            logger.debug("getting replicaset status")
            code, lines = shell("echo 'JSON.stringify(rs.status())' | mongo localhost:27018 --quiet")
            assert code == 0, 'failed to connect to local pod (is it dead ?)'
            return json.loads(' '.join(lines))

        @staticmethod
        def rs_initiate(pods):
            """
            Executes rs.initiate(...) against the local mongod. The _id of members is pod['seq'] and
            host is pod['ip']:pod['ports']['27018']
            """
            rs_name = os.getenv('REPLSET_NAME', 'rs0')
            rs_config_doc = {'_id': rs_name, 'members': []}
            for pod in pods:
                rs_config_doc['members'].append({
                    '_id': pod['seq'],
                    'host': "%s:%d" % (pod['ip'], pod['ports']['27018'])
                })
            # configure
            jsonstr = json.dumps(rs_config_doc)
            logger.info("initializing replicaset %s", rs_config_doc)
            code, _ = shell("echo 'rs.initiate(%s)' | mongo localhost:27018 --quiet" % jsonstr)
            assert code == 0, 'Unable to do rs.initiate(%s)' % rs_config_doc

        @staticmethod
        def rs_add(pod):
            """
            Add the pod as a replicaset member using rs.add({_id: pod['seq'], host: pod['ip']:pod['ports']['27018']})
            """
            hoststr = "%s:%d" % (pod['ip'], pod['ports']['27018'])
            doc = {'_id': pod['seq'], 'host': hoststr}
            jsonstr = json.dumps(doc)
            code, _ = shell("echo 'rs.add(%s)' | mongo localhost:27018 --quiet" % jsonstr)
            assert code == 0, 'Unable to do rs.add(%s)' % jsonstr

        @staticmethod
        def rs_remove(member):
            """
            Remove the given host from replicaset using rs.remove(...)
            """
            code, _ = shell("echo 'rs.remove(\"%s\")' | mongo localhost:27018 --quiet" % member['name'])
            assert code == 0, 'Unable to do rs.remove(\"%s\")' % member

        @staticmethod
        def find_pod_for_member(pods, member):
            for pod in pods:
                if pod['seq'] == member['_id']:
                    return pod
            return None

        @staticmethod
        def find_member_for_pod(members, pod):
            for member in members:
                if member['_id'] == pod['seq']:
                    return member
            return None

        def probe(self, cluster):
            """
            This method looks at the cluster description, reconciles the replicaset configuration
            and then performs a rs.status() check against all members to ensure that there is at
            least one primary node and all other nodes are in states <= 5
            http://docs.mongodb.org/manual/reference/replica-states/
            :param cluster: Cluster configuration passed by ochopod
            :return: status string - rs.status() response as json
            """
            primary = None
            secondaries = []
            pods = cluster.pods.values()
            props = self.rs_status()
            # log pods and replSet status
            logger.debug("list of pods -> %s", pods)
            logger.debug("rs.status() -> %s", props)
            if props['ok'] == 0:
                self.rs_initiate(pods)
                props = self.rs_status()
                return json.dumps(props)
            else:
                logger.debug("Checking status of existing replset")
                members = props['members']
                # now add any new pods that have shown up
                for pod in pods:
                    matching_member = self.find_member_for_pod(members, pod)
                    if matching_member is None:
                        logger.info('Adding new pod: %s as a member', pod)
                        self.rs_add(pod)
                    else:
                        # found the member in pod as member
                        logger.debug('Found member matching pod: %s -> %s', pod, matching_member)
                # now remove any members that are no longer in the list of pods
                members = self.rs_status()['members']
                logger.info("remove stale pods")
                for member in members:
                    matching_pod = self.find_pod_for_member(pods, member)
                    if matching_pod is None:
                        logger.info('Removing member %s - pod not present in list', member)
                        self.rs_remove(member)
                # refresh the replicaset status
                props = self.rs_status()
            # get configuration and get status
            members = props['members']
            for pod in pods:
                member = self.find_member_for_pod(members, pod)
                assert member, 'unable to find pod: %d is list of members' % (pod['seq'])
                state = member['state']
                assert state <= 5, 'pod #%d -> <%s>' % (pod['seq'], member['stateStr'])
                if state == 1:
                    primary = member
                elif state in [0, 2, 3, 5]:
                    secondaries.append(member)
            # assert we found a primary
            assert primary, 'no primary found ?'
            # assert that all nodes other than the primary are either secondaries or are in
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

        def initialize(self):
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

        def configure(self, cluster):
            return 'mongod --config /etc/mongod.yaml', {}


    Pod().boot(Strategy, model=Model)
