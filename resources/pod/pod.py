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

        def probe(self, cluster):

            #
            # - check each pod and issue a MNTR command
            # - the goal is to make sure they are all part of the ensemble
            #
            leader = None
            for key, pod in cluster.pods.items():

                ip = pod['ip'] if key != cluster.key else 'localhost'
                port = pod['ports']['2181'] if key != cluster.key else '2181'
                code, lines = shell('echo mntr | nc -w 5 %s %s' % (ip, port))
                assert code == 0, 'failed to connect to pod #%d (is it dead ?)' % pod['seq']

                props = {}
                for line in lines:
                    if line:
                        tokens = line.split('\t')
                        props[tokens[0]] = ' '.join(tokens[1:])

                assert 'zk_server_state' in props, 'pod #%d -> not serving requests (is zk down ?)' % pod['seq']

                state = props['zk_server_state']
                assert state in ['leader', 'follower'], 'pod #%d -> <%s>' % (pod['seq'], state)
                if state == 'leader':
                    leader = props

            assert leader, 'no leader found ?'
            assert int(leader['zk_synced_followers']) == cluster.size - 1, '1+ follower not synced'
            return '%s zk nodes / ~ %s KB' % (leader['zk_znode_count'], leader['zk_approximate_data_size'])

    class Strategy(Piped):

        cwd = '/opt/zookeeper-3.4.6'

        strict = True

        check_every = 60.0

        pid = None

        since = 0.0

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
            # - assign the server/id bindings to enable clustering
            # - lookup the port mappings for each pod (TCP 2888 and 3888)
            #
            peers = {}
            local = cluster.index + 1
            for n, key in enumerate(sorted(cluster.pods.keys()), 1):
                pod = cluster.pods[key]
                suffix = '%d:%d' % (pod['ports']['2888'], pod['ports']['3888'])
                peers[n] = '%s:%s' % (pod['ip'], suffix)

            # - set "this" node as 0.0.0.0:2888:3888
            # - i've observed weird behavior with docker 1.3 where zk can't bind the address if specified
            #
            peers[local] = '0.0.0.0:2888:3888'
            logger.debug('local id #%d, peer configuration ->\n%s' %
                         (local, '\n'.join(['\t#%d\t-> %s' % (n, mapping) for n, mapping in peers.items()])))

            #
            # - set our server index
            #
            template = Template('{{id}}')
            with open('/var/lib/zookeeper/myid', 'wb') as f:
                f.write(template.render(id=local))

            #
            # - render the zk config template with our peer bindings
            #
            env = Environment(loader=FileSystemLoader(join(dirname(__file__), 'templates')))
            template = env.get_template('zoo.cfg')
            mapping = \
                {
                    'peers': peers
                }

            with open('%s/conf/zoo.cfg' % self.cwd, 'wb') as f:
                f.write(template.render(mapping))

            return 'bin/zkServer.sh start-foreground', {'SERVER_JVMFLAGS': '-Xmx2g'}

    Pod().boot(Strategy, model=Model)