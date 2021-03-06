#
# Celery configuration file
# See: docs.celeryproject.org/en/latest/userguide/configuration.html
#

# Broker URL
# This might be more appropriate in prod:
# broker_url = amqps://user:password@hostname:port//vhost
# broker_use_ssl =
#   keyfile=/var/ssl/private/worker-key.pem
#   certfile=/var/ssl/amqp-server-cert.pem
#   ca_certs=/var/ssl/myca.pem
#   cert_reqs=ssl.CERT_REQUIRED
broker_url = "amqp://rabbitmq/"

# Where the tasks are defined
imports = "bodhi.server.tasks"

# Task routing
task_routes = {
    # Route the following tasks to a specific queue that will only be run on
    # hosts that have a Koji mount.
    'compose': {'queue': 'has_koji_mount'},
    'clean_old_composes': {'queue': 'has_koji_mount'},
}

# We want to store the tasks results to inspect them in tests.
result_backend = "file:///srv/celery-results"
