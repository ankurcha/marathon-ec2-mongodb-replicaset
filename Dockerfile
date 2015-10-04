FROM phusion/baseimage:14.04

# Install Autodesk ochopod and MongoDB.
RUN \
  apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 7F0CEB10 && \
  echo 'deb http://downloads-distro.mongodb.org/repo/ubuntu-upstart dist 10gen' > /etc/apt/sources.list.d/mongodb.list && \
  apt-get update && apt-get install -y mongodb-org curl python python-requests git && \
  curl https://bootstrap.pypa.io/get-pip.py | python && pip install git+https://github.com/autodesk-cloud/ochopod.git && \
  apt-get -y remove git && apt-get -y autoremove && rm -rf /var/lib/apt/lists/* && \
  mkdir -p /var/lib/mongodb

RUN mkdir /etc/service/mongod
# install manager process
ADD resources/pod /opt/mongod/pod
# install runit script
ADD resources/runit/mongod.sh /etc/service/mongod/run

# start processes
CMD ["/sbin/my_init"]
