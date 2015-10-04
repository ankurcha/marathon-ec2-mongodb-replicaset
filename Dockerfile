FROM ubuntu:14.04
ENV DEBIAN_FRONTEND noninteractive

MAINTAINER Ankur Chauhan

# Install Autodesk ochopod and MongoDB.
RUN \
  apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 7F0CEB10 && \
  echo 'deb http://downloads-distro.mongodb.org/repo/ubuntu-upstart dist 10gen' > /etc/apt/sources.list.d/mongodb.list && \
  apt-get update && \
  apt-get install -y mongodb-org curl python python-requests supervisor && \
  curl https://bootstrap.pypa.io/get-pip.py | python && \
  pip install git+https://github.com/autodesk-cloud/ochopod.git && \
  apt-get -y autoremove && \
  rm -rf /var/lib/apt/lists/* && \
  mkdir -p /var/lib/mongodb

ADD resources/pod /opt/mongod/pod
ADD resources/supervisor /etc/supervisor/conf.d
CMD /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
