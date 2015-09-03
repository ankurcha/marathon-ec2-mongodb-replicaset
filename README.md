## Ochothon flask sample

### Overview

This project is a simple [**Docker**](https://www.docker.com/) container definition that can be launched on
[**DCOS from Mesosphere**](https://mesosphere.com/). It illustrates how our [**Ochopod**](https://github.com/autodesk-cloud/ochothon)
technology can be used to manage [**Zookeeper 3.4.6**](http://zookeeper.apache.org) and automatically configure it
into a functional ensemble.


### Deploy it !

Make sure you have [**DCOS**](https://mesosphere.com/) setup over EC2. Then simply blast our little application JSON
payload to one of your masters. For instance:

```
$ curl -s -XPOST http://<YOUR MASTER IP>:8080/v2/apps -d@dcos.json -H "Content-Type: application/json"
```

Wait a bit for the image to be pulled and you will end up with a 3 nodes ensemble ! You can scale your
[**Marathon**](https://mesosphere.github.io/marathon/) task up and down and Ochopod will re-configure your ensemble !

Please note the JSON definition used for this example is not binding TCP 2181 to the host machine so you will have to
see what port it has been remapped to if you want for instance to use this ensemble or send 4-letters commands.

Once you are done playing you can simply destroy the *zookeeper-sample* application.

### Support

Contact autodesk.cloud.opensource@autodesk.com for more information about this project.


### License

© 2015 Autodesk Inc.
All rights reserved

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.