ARG BUILD_FROM
FROM ${BUILD_FROM}

# Python + the publisher's runtime deps
RUN apk add --no-cache python3 py3-pip \
    && pip3 install --no-cache-dir --break-system-packages paho-mqtt influxdb pyyaml

# App
COPY rpi_mqtt_publisher.py /app/rpi_mqtt_publisher.py
COPY publisher.default.yaml /app/publisher.default.yaml
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
