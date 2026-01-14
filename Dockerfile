FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    openssh-client \
    git \
    rsync \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ansible

WORKDIR /ansible
COPY . /ansible

CMD ["ansible-playbook", "--version"]
